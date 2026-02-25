"""
django_sync_api/views.py
=========================
Sync API views for PrimeBooks Desktop.

DROP these 4 endpoints into your existing Django project:
  POST  /api/v1/auth/login/        → Desktop login + JWT
  GET   /api/v1/sync/ping/         → Connectivity check
  GET   /api/v1/sync/pull/         → Pull changes since last_pulled_at
  POST  /api/v1/sync/push/         → Push local dirty records

All views are tenant-aware (django-tenants schema routing works automatically
since the desktop sends X-Schema-Name header which maps to the domain).

HOW TO PLUG IN:
  1. Copy this file to your_project/sync_api/views.py
  2. Copy serializers.py to your_project/sync_api/serializers.py
  3. Copy urls.py content to your_project/sync_api/urls.py
  4. Include in your tenant urlconf:
       path('api/v1/', include('sync_api.urls'))
"""

import time
import logging
from datetime import datetime, timezone as tz

from django.db import transaction, connection
from django.utils import timezone
from django.contrib.auth import authenticate

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from inventory.models import Category, Supplier, Product, Stock, StockMovement
from stores.models import Store
from accounts.models import CustomUser
from .serializers import (
    StoreSyncSerializer, UserSyncSerializer,
    CategorySyncSerializer, CategoryWriteSerializer,
    SupplierSyncSerializer,
    ProductSyncSerializer, ProductWriteSerializer,
    StockSyncSerializer,
    CustomerSyncSerializer, CustomerWriteSerializer,
    SaleSyncSerializer, ExpenseSyncSerializer,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Login
# ─────────────────────────────────────────────────────────────────────────────

class DesktopLoginView(APIView):
    """
    POST /api/v1/auth/login/
    {email, password, schema_name}

    Returns JWT tokens + user profile for offline caching.
    The schema_name must match a valid tenant domain.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')
        schema_name = request.data.get('schema_name', '').strip()

        if not all([email, password, schema_name]):
            return Response(
                {'error': 'email, password, and schema_name are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Authenticate
        user = authenticate(request, email=email, password=password)
        if not user:
            return Response(
                {'error': 'Invalid email or password'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {'error': 'Account is inactive. Contact your administrator.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Verify user belongs to correct company/schema
        if user.company and user.company.schema_name != schema_name:
            return Response(
                {'error': 'Invalid company ID for this account'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        # Build user payload (cached by desktop for offline use)
        user_data = {
            'sync_id': str(user.sync_id),
            'email': user.email,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'company_id': str(user.company.sync_id) if user.company else '',
            'company_name': user.company.name if user.company else '',
            'schema_name': user.company.schema_name if user.company else '',
            'role_name': user.display_role,
            'role_priority': user.highest_role_priority,
            'permissions': list(user.get_all_permissions()),
            'is_company_admin': user.company_admin,
            'timezone': user.timezone,
            'language': user.language,
            'default_store_id': str(user.metadata.get('default_store_id', '')) if user.metadata else '',
        }

        logger.info(f"Desktop login: {email} → schema={schema_name}")

        return Response({
            'user': user_data,
            'tokens': {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'expires_in': 3600,  # seconds
            }
        })


# ─────────────────────────────────────────────────────────────────────────────
# 2. Ping
# ─────────────────────────────────────────────────────────────────────────────

class SyncPingView(APIView):
    """
    GET /api/v1/sync/ping/
    Quick connectivity check. Returns server time for clock-skew detection.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            'status': 'ok',
            'server_time': time.time(),
            'schema': connection.schema_name,
        })


# ─────────────────────────────────────────────────────────────────────────────
# 3. Pull
# ─────────────────────────────────────────────────────────────────────────────

class SyncPullView(APIView):
    """
    GET /api/v1/sync/pull/
    ?last_pulled_at=<unix_ts>
    &tables=stores,users,categories,suppliers,products,stock,customers,sales,expenses

    Returns all records changed AFTER last_pulled_at.
    Records with is_deleted=True are returned in the 'deleted' arrays.

    Performance notes:
    - Uses updated_at index on every table
    - select_related() to avoid N+1 queries
    - Streams only changed fields (not the full schema)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        last_pulled_at_ts = request.query_params.get('last_pulled_at', '0')
        tables_param = request.query_params.get('tables', '')

        try:
            last_pulled_at_ts = float(last_pulled_at_ts)
        except (ValueError, TypeError):
            last_pulled_at_ts = 0.0

        # Convert Unix timestamp to Django datetime
        if last_pulled_at_ts > 0:
            last_pulled_dt = datetime.fromtimestamp(last_pulled_at_ts, tz=tz.utc)
        else:
            last_pulled_dt = None

        requested_tables = set(tables_param.split(',')) if tables_param else None

        server_timestamp = time.time()
        changes = {}

        def should_include(table_name):
            return requested_tables is None or table_name in requested_tables

        # ── Stores ─────────────────────────────────────────────────────────
        if should_include('stores'):
            changes['stores'] = self._pull_stores(last_pulled_dt)

        # ── Users ──────────────────────────────────────────────────────────
        if should_include('users'):
            changes['users'] = self._pull_users(request.user, last_pulled_dt)

        # ── Categories ────────────────────────────────────────────────────
        if should_include('categories'):
            changes['categories'] = self._pull_model(
                Category, CategorySyncSerializer, last_pulled_dt,
                filter_kwargs={'updated_at__isnull': False},
                order_by='updated_at',
            )

        # ── Suppliers ─────────────────────────────────────────────────────
        if should_include('suppliers'):
            changes['suppliers'] = self._pull_model(
                Supplier, SupplierSyncSerializer, last_pulled_dt,
                order_by='updated_at',
            )

        # ── Products ──────────────────────────────────────────────────────
        if should_include('products'):
            changes['products'] = self._pull_model(
                Product, ProductSyncSerializer, last_pulled_dt,
                select_related=['category', 'supplier'],
                order_by='updated_at',
            )

        # ── Stock ─────────────────────────────────────────────────────────
        if should_include('stock'):
            changes['stock'] = self._pull_stock(last_pulled_dt)

        # ── Customers ─────────────────────────────────────────────────────
        if should_include('customers'):
            try:
                from customers.models import Customer
                changes['customers'] = self._pull_model(
                    Customer, CustomerSyncSerializer, last_pulled_dt,
                    order_by='updated_at',
                )
            except ImportError:
                changes['customers'] = _empty_changes()

        # ── Sales ─────────────────────────────────────────────────────────
        if should_include('sales'):
            try:
                from sales.models import Sale
                changes['sales'] = self._pull_sales(Sale, last_pulled_dt)
            except ImportError:
                changes['sales'] = _empty_changes()

        # ── Expenses ──────────────────────────────────────────────────────
        if should_include('expenses'):
            try:
                from expenses.models import Expense
                changes['expenses'] = self._pull_model(
                    Expense, ExpenseSyncSerializer, last_pulled_dt,
                    select_related=['store', 'created_by'],
                    order_by='updated_at',
                )
            except ImportError:
                changes['expenses'] = _empty_changes()

        total_changes = sum(
            len(v.get('created', [])) + len(v.get('updated', [])) + len(v.get('deleted', []))
            for v in changes.values()
        )
        logger.info(
            f"Pull: user={request.user.email}, "
            f"since={last_pulled_at_ts}, total_changes={total_changes}"
        )

        return Response({
            'timestamp': server_timestamp,
            'changes': changes,
        })

    def _pull_model(self, model_class, serializer_class, last_pulled_dt,
                    filter_kwargs=None, select_related=None, order_by='updated_at'):
        """Generic pull for any model with updated_at + sync_id."""
        qs = model_class.objects.all()

        if select_related:
            qs = qs.select_related(*select_related)

        if filter_kwargs:
            qs = qs.filter(**filter_kwargs)

        if last_pulled_dt:
            changed_qs = qs.filter(updated_at__gt=last_pulled_dt)
        else:
            # First sync — return everything
            changed_qs = qs

        changed_qs = changed_qs.order_by(order_by)

        # Split active vs deleted
        try:
            active = [r for r in changed_qs if not getattr(r, 'is_deleted', False)]
            deleted_ids = [str(r.sync_id) for r in changed_qs if getattr(r, 'is_deleted', False)]
        except Exception:
            active = list(changed_qs)
            deleted_ids = []

        if last_pulled_dt:
            # On subsequent syncs, separate truly new vs updated
            created_ids = set(
                str(r.sync_id) for r in model_class.objects.filter(
                    created_at__gt=last_pulled_dt
                ).values_list('sync_id', flat=True)
            )
            created = [r for r in active if str(r.sync_id) in created_ids]
            updated = [r for r in active if str(r.sync_id) not in created_ids]
        else:
            created = active
            updated = []

        return {
            'created': serializer_class(created, many=True).data,
            'updated': serializer_class(updated, many=True).data,
            'deleted': deleted_ids,
        }

    def _pull_stores(self, last_pulled_dt):
        qs = Store.objects.filter(is_active=True)
        if last_pulled_dt:
            qs = qs.filter(updated_at__gt=last_pulled_dt)
        return {
            'created': StoreSyncSerializer(qs, many=True).data,
            'updated': [],
            'deleted': [],
        }

    def _pull_users(self, requesting_user, last_pulled_dt):
        """Pull users that belong to the same company."""
        qs = CustomUser.objects.filter(
            company=requesting_user.company,
            is_hidden=False,
            is_active=True,
        )
        if last_pulled_dt:
            qs = qs.filter(last_activity_at__gt=last_pulled_dt)

        return {
            'created': UserSyncSerializer(qs, many=True).data,
            'updated': [],
            'deleted': [],
        }

    def _pull_stock(self, last_pulled_dt):
        qs = Stock.objects.select_related('product', 'store')
        if last_pulled_dt:
            qs = qs.filter(last_updated__gt=last_pulled_dt)
        return {
            'created': StockSyncSerializer(qs, many=True).data,
            'updated': [],
            'deleted': [],
        }

    def _pull_sales(self, Sale, last_pulled_dt):
        qs = Sale.objects.select_related(
            'store', 'customer', 'created_by'
        ).prefetch_related('items__product')

        if last_pulled_dt:
            qs = qs.filter(updated_at__gt=last_pulled_dt)

        return {
            'created': SaleSyncSerializer(qs, many=True).data,
            'updated': [],
            'deleted': [],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Push
# ─────────────────────────────────────────────────────────────────────────────

class SyncPushView(APIView):
    """
    POST /api/v1/sync/push/
    {
      "schema_name": "tenant1",
      "changes": {
        "products": {"created": [...], "updated": [...], "deleted": ["uuid", ...]},
        "customers": {...},
        "sales": {...},
        "expenses": {...}
      }
    }

    Returns:
    {
      "accepted": {"products": ["uuid", ...], ...},
      "rejected": {"products": [{"sync_id": ..., "error": ...}], ...},
      "conflicts": {}
    }
    """
    permission_classes = [IsAuthenticated]

    # Map table name → (write_serializer, model_class, read_serializer)
    PUSH_HANDLERS = {
        'categories':  (CategoryWriteSerializer, Category, CategorySyncSerializer),
        'products':    (ProductWriteSerializer, Product, ProductSyncSerializer),
        'customers':   (CustomerWriteSerializer, None, CustomerSyncSerializer),
        'expenses':    (None, None, ExpenseSyncSerializer),
    }

    def post(self, request):
        changes = request.data.get('changes', {})
        if not changes:
            return Response({'accepted': {}, 'rejected': {}, 'conflicts': {}})

        accepted = {}
        rejected = {}
        conflicts = {}

        for table_name, table_changes in changes.items():
            if table_name not in self.PUSH_HANDLERS:
                logger.warning(f"Push: unknown table '{table_name}' — skipping")
                continue

            write_ser_class, model_class, read_ser_class = self.PUSH_HANDLERS[table_name]

            table_accepted = []
            table_rejected = []

            # ── Handle created records ───────────────────────────────────
            for record_data in table_changes.get('created', []):
                result = self._upsert_record(
                    table_name, record_data, write_ser_class, model_class,
                    request.user, is_new=True
                )
                if result['ok']:
                    table_accepted.append(result['sync_id'])
                else:
                    table_rejected.append({'sync_id': result['sync_id'], 'error': result['error']})

            # ── Handle updated records ───────────────────────────────────
            for record_data in table_changes.get('updated', []):
                result = self._upsert_record(
                    table_name, record_data, write_ser_class, model_class,
                    request.user, is_new=False
                )
                if result['ok']:
                    table_accepted.append(result['sync_id'])
                else:
                    table_rejected.append({'sync_id': result['sync_id'], 'error': result['error']})

            # ── Handle soft-deletes ──────────────────────────────────────
            for sync_id in table_changes.get('deleted', []):
                result = self._soft_delete(table_name, sync_id, model_class)
                if result['ok']:
                    table_accepted.append(sync_id)
                else:
                    table_rejected.append({'sync_id': sync_id, 'error': result['error']})

            accepted[table_name] = table_accepted
            rejected[table_name] = table_rejected

        total_accepted = sum(len(v) for v in accepted.values())
        total_rejected = sum(len(v) for v in rejected.values())
        logger.info(
            f"Push: user={request.user.email}, "
            f"accepted={total_accepted}, rejected={total_rejected}"
        )

        return Response({
            'accepted': accepted,
            'rejected': rejected,
            'conflicts': conflicts,
        })

    def _upsert_record(self, table_name, record_data, serializer_class, model_class,
                        user, is_new=True):
        sync_id = record_data.get('sync_id', '')
        if not sync_id:
            return {'ok': False, 'sync_id': '', 'error': 'Missing sync_id'}

        try:
            with transaction.atomic():
                if table_name == 'customers':
                    return self._upsert_customer(record_data, user, is_new)
                elif table_name == 'expenses':
                    return self._upsert_expense(record_data, user, is_new)
                elif table_name == 'sales':
                    return self._upsert_sale(record_data, user, is_new)

                # Generic upsert via serializer
                if model_class is None:
                    return {'ok': False, 'sync_id': sync_id, 'error': 'No handler for table'}

                try:
                    instance = model_class.objects.get(sync_id=sync_id)
                    serializer = serializer_class(instance, data=record_data, partial=True)
                except model_class.DoesNotExist:
                    serializer = serializer_class(data=record_data)

                if serializer.is_valid():
                    instance = serializer.save()
                    return {'ok': True, 'sync_id': str(instance.sync_id)}
                else:
                    return {
                        'ok': False,
                        'sync_id': sync_id,
                        'error': str(serializer.errors)
                    }

        except Exception as e:
            logger.exception(f"Push upsert error: table={table_name}, sync_id={sync_id}")
            return {'ok': False, 'sync_id': sync_id, 'error': str(e)}

    def _upsert_customer(self, data, user, is_new):
        from customers.models import Customer
        sync_id = data.get('sync_id')
        try:
            customer, created = Customer.objects.update_or_create(
                sync_id=sync_id,
                defaults={
                    'name': data.get('name', ''),
                    'email': data.get('email', ''),
                    'phone': data.get('phone', ''),
                    'address': data.get('address', ''),
                    'tin': data.get('tin') or None,
                    'is_active': data.get('is_active', True),
                    'credit_limit': float(data.get('credit_limit', 0) or 0),
                }
            )
            return {'ok': True, 'sync_id': str(customer.sync_id)}
        except Exception as e:
            return {'ok': False, 'sync_id': sync_id, 'error': str(e)}

    def _upsert_expense(self, data, user, is_new):
        from expenses.models import Expense
        from datetime import datetime
        sync_id = data.get('sync_id')
        try:
            expense_date = None
            if data.get('expense_date'):
                expense_date = datetime.fromtimestamp(float(data['expense_date']))

            store = None
            if data.get('store_id'):
                try:
                    store = Store.objects.get(sync_id=data['store_id'])
                except Store.DoesNotExist:
                    pass

            expense, _ = Expense.objects.update_or_create(
                sync_id=sync_id,
                defaults={
                    'title': data.get('title', ''),
                    'description': data.get('description', ''),
                    'amount': float(data.get('amount', 0) or 0),
                    'expense_date': expense_date,
                    'category': data.get('category', ''),
                    'payment_method': data.get('payment_method', 'cash'),
                    'reference': data.get('reference', ''),
                    'store': store,
                    'created_by': user,
                    'status': data.get('status', 'pending'),
                    'notes': data.get('notes', ''),
                }
            )
            return {'ok': True, 'sync_id': str(expense.sync_id)}
        except Exception as e:
            return {'ok': False, 'sync_id': sync_id, 'error': str(e)}

    def _upsert_sale(self, data, user, is_new):
        """
        Sales push is complex — creates sale + items atomically.
        Stock deduction is NOT done here (already done locally on desktop).
        """
        from sales.models import Sale, SaleItem
        sync_id = data.get('sync_id')

        try:
            store = Store.objects.get(sync_id=data['store_id'])

            customer = None
            if data.get('customer_id'):
                try:
                    from customers.models import Customer
                    customer = Customer.objects.get(sync_id=data['customer_id'])
                except Exception:
                    pass

            sale, created = Sale.objects.update_or_create(
                sync_id=sync_id,
                defaults={
                    'document_number': data.get('document_number', ''),
                    'store': store,
                    'customer': customer,
                    'created_by': user,
                    'subtotal': float(data.get('subtotal', 0) or 0),
                    'tax_amount': float(data.get('tax_amount', 0) or 0),
                    'discount_amount': float(data.get('discount_amount', 0) or 0),
                    'total_amount': float(data.get('total_amount', 0) or 0),
                    'amount_paid': float(data.get('amount_paid', 0) or 0),
                    'change_amount': float(data.get('change_amount', 0) or 0),
                    'status': data.get('status', 'completed'),
                    'payment_method': data.get('payment_method', 'cash'),
                    'payment_status': data.get('payment_status', 'paid'),
                    'notes': data.get('notes', ''),
                }
            )

            # Sync items only on create (updates to sales items not supported via push)
            if created:
                for item_data in data.get('items', []):
                    try:
                        product = Product.objects.get(sync_id=item_data['product_id'])
                        SaleItem.objects.update_or_create(
                            sync_id=item_data.get('sync_id'),
                            defaults={
                                'sale': sale,
                                'product': product,
                                'quantity': float(item_data.get('quantity', 1)),
                                'unit_price': float(item_data.get('unit_price', 0)),
                                'discount_percentage': float(item_data.get('discount_percentage', 0)),
                                'tax_rate': item_data.get('tax_rate', 'A'),
                                'tax_amount': float(item_data.get('tax_amount', 0)),
                                'subtotal': float(item_data.get('subtotal', 0)),
                                'total': float(item_data.get('total', 0)),
                            }
                        )
                    except Product.DoesNotExist:
                        logger.warning(f"Push sale: product {item_data.get('product_id')} not found")

            return {'ok': True, 'sync_id': str(sale.sync_id)}
        except Exception as e:
            logger.exception(f"Push sale error: {e}")
            return {'ok': False, 'sync_id': sync_id, 'error': str(e)}

    def _soft_delete(self, table_name, sync_id, model_class):
        if model_class is None:
            return {'ok': False, 'sync_id': sync_id, 'error': 'Soft delete not supported'}
        try:
            obj = model_class.objects.get(sync_id=sync_id)
            if hasattr(obj, 'is_active'):
                obj.is_active = False
                obj.save(update_fields=['is_active'])
            return {'ok': True, 'sync_id': sync_id}
        except model_class.DoesNotExist:
            return {'ok': True, 'sync_id': sync_id}  # Already gone = accepted
        except Exception as e:
            return {'ok': False, 'sync_id': sync_id, 'error': str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _empty_changes():
    return {'created': [], 'updated': [], 'deleted': []}