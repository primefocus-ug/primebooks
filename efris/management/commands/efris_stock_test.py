from django.core.management.base import BaseCommand
from django.utils import timezone
from django_tenants.utils import schema_context, get_tenant_model
from inventory.models import Product, Stock, StockMovement, Supplier, Category
from stores.models import Store
from efris.services import EnhancedEFRISAPIClient
import json


class Command(BaseCommand):
    help = 'Test EFRIS stock management integration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            required=True,
            help='Tenant schema name or domain'
        )
        parser.add_argument(
            '--test',
            type=str,
            choices=[
                'query_stock',
                'increase_stock',
                'decrease_stock',
                'transfer_stock',
                'sync_movement',
                'bulk_sync',
                'query_records',
                'full_test'
            ],
            default='full_test',
            help='Which test to run'
        )
        parser.add_argument('--product-sku', type=str, help='Product SKU to test with')
        parser.add_argument('--store-id', type=int, help='Store ID to test with')
        parser.add_argument('--quantity', type=float, default=10.0, help='Quantity for stock operations')

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('\n=== EFRIS Stock Management Test ===\n'))

        # Get tenant
        try:
            Tenant = get_tenant_model()
            tenant_identifier = options['tenant']

            # Try to get tenant by schema_name or domain
            try:
                tenant = Tenant.objects.get(schema_name=tenant_identifier)
            except Tenant.DoesNotExist:
                # Try by domain
                from django_tenants.utils import get_tenant_domain_model
                Domain = get_tenant_domain_model()
                domain = Domain.objects.select_related('tenant').get(domain=tenant_identifier)
                tenant = domain.tenant

            self.stdout.write(self.style.SUCCESS(f'✓ Using tenant: {tenant.schema_name}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to get tenant: {e}'))
            self.stdout.write(self.style.WARNING('Available tenants:'))
            for t in Tenant.objects.all():
                self.stdout.write(f'  - {t.schema_name}')
            return

        # Execute within tenant schema
        with schema_context(tenant.schema_name):
            try:
                # Get company from tenant
                company = tenant

                # Initialize EFRIS client
                client = EnhancedEFRISAPIClient(company)

                self.stdout.write(self.style.SUCCESS('✓ EFRIS client initialized'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to initialize EFRIS client: {e}'))
                import traceback
                traceback.print_exc()
                return

            # Get test product
            product = self._get_test_product(options.get('product_sku'))
            if not product:
                return

            # Get test store
            store = self._get_test_store(options.get('store_id'))
            if not store:
                return

            # Run selected test
            test_type = options['test']

            try:
                if test_type == 'query_stock':
                    self._test_query_stock(client, product)
                elif test_type == 'increase_stock':
                    self._test_increase_stock(client, product, store, options['quantity'])
                elif test_type == 'decrease_stock':
                    self._test_decrease_stock(client, product, store, options['quantity'])
                elif test_type == 'transfer_stock':
                    self._test_transfer_stock(client, product, store)
                elif test_type == 'sync_movement':
                    self._test_sync_movement(client, product, store, options['quantity'])
                elif test_type == 'bulk_sync':
                    self._test_bulk_sync(client, store)
                elif test_type == 'query_records':
                    self._test_query_records(client)
                elif test_type == 'full_test':
                    self._run_full_test(client, product, store, options['quantity'])
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Test failed: {e}'))
                import traceback
                traceback.print_exc()

    def _get_test_product(self, sku=None):
        """Get a test product"""
        if sku:
            try:
                product = Product.objects.get(sku=sku)
            except Product.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Product with SKU {sku} not found'))
                return None
        else:
            product = Product.objects.filter(
                efris_goods_id__isnull=False,
                is_active=True
            ).first()

            if not product:
                self.stdout.write(self.style.ERROR('No products with EFRIS ID found. Upload products first.'))
                return None

        if not product.efris_goods_id:
            self.stdout.write(self.style.ERROR(f'Product {product.sku} has no EFRIS goods ID'))
            self.stdout.write(self.style.WARNING('Upload product to EFRIS first'))
            return None

        self.stdout.write(self.style.SUCCESS(f'✓ Using product: {product.name} (SKU: {product.sku})'))
        self.stdout.write(f'  EFRIS Goods ID: {product.efris_goods_id}')

        return product

    def _get_test_store(self, store_id=None):
        """Get a test store"""
        if store_id:
            try:
                store = Store.objects.get(id=store_id)
            except Store.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Store with ID {store_id} not found'))
                return None
        else:
            store = Store.objects.filter(is_active=True).first()

            if not store:
                self.stdout.write(self.style.ERROR('No active stores found'))
                return None

        self.stdout.write(self.style.SUCCESS(f'✓ Using store: {store.name}'))

        if hasattr(store, 'efris_branch_id'):
            self.stdout.write(f'  EFRIS Branch ID: {store.efris_branch_id}')
        else:
            self.stdout.write(self.style.WARNING('  Warning: Store has no efris_branch_id'))

        return store

    def _test_query_stock(self, client, product):
        """Test T128: Query stock by goods ID"""
        self.stdout.write(self.style.HTTP_INFO('\n--- Test: Query Stock (T128) ---'))

        try:
            result = client.t128_query_stock_by_goods_id(product.efris_goods_id)

            self.stdout.write(self.style.SUCCESS('✓ Query successful'))
            self.stdout.write(f'  EFRIS Stock: {result.get("stock", "N/A")}')
            self.stdout.write(f'  Stock Warning: {result.get("stockPrewarning", "N/A")}')

            local_stock = product.total_stock
            self.stdout.write(f'  Local Stock: {local_stock}')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed: {e}'))
            import traceback
            traceback.print_exc()

    def _test_increase_stock(self, client, product, store, quantity):
        """Test T131: Increase stock"""
        self.stdout.write(self.style.HTTP_INFO(f'\n--- Test: Increase Stock (T131) ---'))
        self.stdout.write(f'Adding {quantity} units to {product.name}')

        try:
            stock, created = Stock.objects.get_or_create(
                product=product,
                store=store,
                defaults={'quantity': 0}
            )

            old_quantity = stock.quantity

            result = client.increase_stock_from_product(
                product=product,
                quantity=quantity,
                store=store,
                stock_in_type="102",
                supplier_name=product.supplier.name if product.supplier else store.name,
                supplier_tin=product.supplier.tin if product.supplier else None
            )

            self.stdout.write(self.style.SUCCESS('✓ EFRIS request successful'))
            self.stdout.write(json.dumps(result, indent=2))

            stock.quantity = float(stock.quantity) + quantity
            stock.save()

            self.stdout.write(self.style.SUCCESS(f'✓ Local stock updated: {old_quantity} → {stock.quantity}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed: {e}'))
            import traceback
            traceback.print_exc()

    def _test_decrease_stock(self, client, product, store, quantity):
        """Test T131: Decrease stock"""
        self.stdout.write(self.style.HTTP_INFO(f'\n--- Test: Decrease Stock (T131) ---'))
        self.stdout.write(f'Removing {quantity} units from {product.name}')

        try:
            stock = Stock.objects.filter(product=product, store=store).first()

            if not stock or stock.quantity < quantity:
                self.stdout.write(self.style.ERROR(f'Insufficient stock. Available: {stock.quantity if stock else 0}'))
                return

            old_quantity = stock.quantity

            result = client.decrease_stock_from_product(
                product=product,
                quantity=quantity,
                store=store,
                adjust_type="105",
                remarks="Test stock reduction"
            )

            self.stdout.write(self.style.SUCCESS('✓ EFRIS request successful'))
            self.stdout.write(json.dumps(result, indent=2))

            stock.quantity = float(stock.quantity) - quantity
            stock.save()

            self.stdout.write(self.style.SUCCESS(f'✓ Local stock updated: {old_quantity} → {stock.quantity}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed: {e}'))

    def _test_query_records(self, client):
        """Test querying stock records"""
        self.stdout.write(self.style.HTTP_INFO('\n--- Test: Query Stock Records ---'))

        try:
            from datetime import timedelta
            result = client.t147_query_stock_records_advanced(
                start_date=(timezone.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
                end_date=timezone.now().strftime('%Y-%m-%d'),
                page_no="1",
                page_size="5"
            )

            self.stdout.write(self.style.SUCCESS('✓ Query successful'))
            self.stdout.write(f'  Total records: {result.get("page", {}).get("totalSize", 0)}')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed: {e}'))

    def _test_sync_movement(self, client, product, store, quantity):
        """Test syncing a StockMovement to EFRIS"""
        self.stdout.write(self.style.HTTP_INFO('\n--- Test: Sync Stock Movement ---'))

        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.first()

            movement = StockMovement.objects.create(
                product=product,
                store=store,
                movement_type='PURCHASE',
                quantity=quantity,
                unit_price=product.cost_price,
                reference=f'TEST-PURCHASE-{timezone.now().strftime("%Y%m%d%H%M%S")}',
                notes='Test purchase from supplier',
                created_by=user
            )

            self.stdout.write(f'Created movement: {movement}')

            result = client.t131_maintain_stock_from_movement(
                movement=movement,
                supplier_name=product.supplier.name if product.supplier else store.name,
                supplier_tin=product.supplier.tin if product.supplier else None
            )

            self.stdout.write(self.style.SUCCESS('✓ Movement synced to EFRIS'))
            self.stdout.write(json.dumps(result, indent=2))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed: {e}'))

    def _test_bulk_sync(self, client, store=None):
        """Test bulk sync of pending stocks"""
        self.stdout.write(self.style.HTTP_INFO('\n--- Test: Bulk Stock Sync ---'))

        try:
            pending_stocks = Stock.objects.filter(
                product__efris_goods_id__isnull=False
            )[:5]

            if store:
                pending_stocks = pending_stocks.filter(store=store)

            pending_stocks.update(efris_sync_required=True)

            self.stdout.write(f'Marked {pending_stocks.count()} stocks for sync')

            result = client.bulk_sync_stock_to_efris(store=store)

            self.stdout.write(self.style.SUCCESS('✓ Bulk sync completed'))
            self.stdout.write(f'  Total: {result["total"]}')
            self.stdout.write(f'  Successful: {result["successful"]}')
            self.stdout.write(f'  Failed: {result["failed"]}')

            if result["errors"]:
                self.stdout.write(self.style.WARNING('\nErrors:'))
                for error in result["errors"]:
                    self.stdout.write(f'  - {error["product"]} @ {error["store"]}: {error["error"]}')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed: {e}'))

    def _test_transfer_stock(self, client, product, source_store):
        """Test T139: Transfer stock between stores"""
        self.stdout.write(self.style.HTTP_INFO('\n--- Test: Transfer Stock (T139) ---'))

        dest_store = Store.objects.exclude(id=source_store.id).filter(is_active=True).first()

        if not dest_store:
            self.stdout.write(self.style.WARNING('Need at least 2 stores for transfer test'))
            return

        if not hasattr(source_store, 'efris_branch_id') or not hasattr(dest_store, 'efris_branch_id'):
            self.stdout.write(self.style.WARNING('Stores need efris_branch_id for transfers'))
            return

        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.first()

            quantity = 5.0

            movement = StockMovement.objects.create(
                product=product,
                store=source_store,
                movement_type='TRANSFER_OUT',
                quantity=-quantity,
                reference=f'TEST-TRANSFER-{timezone.now().strftime("%Y%m%d%H%M%S")}',
                notes='Test transfer between stores',
                created_by=user
            )

            result = client.t139_transfer_stock_from_movement(
                movement=movement,
                destination_branch_id=dest_store.efris_branch_id
            )

            self.stdout.write(self.style.SUCCESS('✓ Transfer successful'))
            self.stdout.write(json.dumps(result, indent=2))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed: {e}'))

    def _run_full_test(self, client, product, store, quantity):
        """Run all tests sequentially"""
        self.stdout.write(self.style.SUCCESS('\n=== Running Full Test Suite ===\n'))

        tests = [
            ('Query Stock', lambda: self._test_query_stock(client, product)),
            ('Increase Stock', lambda: self._test_increase_stock(client, product, store, quantity)),
            ('Query Stock Again', lambda: self._test_query_stock(client, product)),
            ('Query Records', lambda: self._test_query_records(client)),
        ]

        for test_name, test_func in tests:
            try:
                test_func()
                self.stdout.write(self.style.SUCCESS(f'✓ {test_name} completed\n'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'✗ {test_name} failed: {e}\n'))

        self.stdout.write(self.style.SUCCESS('\n=== Full Test Complete ===\n'))