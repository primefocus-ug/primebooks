# inventory/api/scanner_views.py
"""
Scanner API endpoints.

URL patterns to add to your inventory/urls.py:

    from inventory.api.scanner_views import (
        BarcodeScanView, StockReceiveView, QuickProductCreateView,
        ScanSessionView, BarcodeLabelView,
    )

    urlpatterns += [
        path('api/scan/barcode/',                      BarcodeScanView.as_view(),        name='api-scan-barcode'),
        path('api/scan/receive-stock/',                StockReceiveView.as_view(),       name='api-scan-receive-stock'),
        path('api/scan/quick-create/',                 QuickProductCreateView.as_view(), name='api-scan-quick-create'),
        path('api/scan/session/',                      ScanSessionView.as_view(),        name='api-scan-session'),
        path('api/scan/session/<int:pk>/complete/',    ScanSessionView.as_view(),        name='api-scan-session-complete'),
        path('api/scan/session/<int:pk>/',             ScanSessionView.as_view(),        name='api-scan-session-detail'),
        path('api/scan/labels/',                       BarcodeLabelView.as_view(),       name='api-scan-labels'),
        path('api/scan/search/',                       ProductSearchView.as_view(),      name='api-scan-search'),
    ]
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(['GET'])
def scan_session_page(request):
    """
    Render the scan session UI.
    Determines which modes and stores are accessible based on the user's groups (RBAC).
    """
    from stores.models import Store
    from inventory.models import Category

    user = request.user
    groups = set(user.groups.values_list('name', flat=True))

    if user.is_superuser or 'admin' in groups or 'manager' in groups:
        stores = Store.objects.filter(is_active=True).order_by('name')
    else:
        stores = Store.objects.filter(
            is_active=True,
            staff_members=user,
        ).order_by('name')

    all_modes = [
        ('receive_stock',  'Receive stock delivery'),
        ('stock_count',    'Stock count'),
        ('product_lookup', 'Product lookup'),
        ('pos_checkout',   'POS checkout'),
    ]

    if 'cashier' in groups and not (user.is_superuser or 'admin' in groups):
        available_modes = [m for m in all_modes if m[0] in ('pos_checkout', 'product_lookup')]
    elif 'warehouse' in groups and not (user.is_superuser or 'admin' in groups):
        available_modes = [m for m in all_modes if m[0] in ('receive_stock', 'stock_count')]
    else:
        available_modes = all_modes

    user_default_store_id = None
    try:
        if hasattr(user, 'profile') and user.profile.default_store:
            user_default_store_id = user.profile.default_store.pk
        elif stores.count() == 1:
            user_default_store_id = stores.first().pk
    except Exception:
        pass

    categories = Category.objects.filter(
        is_active=True,
        category_type='product',
    ).values('id', 'name').order_by('name')

    context = {
        'stores': stores,
        'scan_modes': available_modes,
        'user_default_store_id': user_default_store_id,
        'categories_json': json.dumps(list(categories)),
    }
    return render(request, 'inventory/scan_session.html', context)


# ------------------------------------------------------------------ #
#  Permission helpers                                                  #
# ------------------------------------------------------------------ #

def _can_create_products(user):
    if user.is_superuser:
        return True
    groups = set(user.groups.values_list('name', flat=True))
    return bool(groups & {'admin', 'stock_manager', 'manager'})


def _can_receive_stock(user):
    if user.is_superuser:
        return True
    groups = set(user.groups.values_list('name', flat=True))
    return bool(groups & {'admin', 'stock_manager', 'warehouse', 'manager'})


def _can_print_labels(user):
    if user.is_superuser:
        return True
    groups = set(user.groups.values_list('name', flat=True))
    return bool(groups & {'admin', 'stock_manager', 'manager'})


# ------------------------------------------------------------------ #
#  0. Product Search — name/SKU/barcode prefix search for UI          #
# ------------------------------------------------------------------ #

class ProductSearchView(APIView):
    """
    GET /api/scan/search/?q=coca&store_id=3

    Fast DB-only typeahead search used by the scan UI's manual search box.
    Returns up to 10 matching active products.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = (request.GET.get('q') or '').strip()
        store_id = request.GET.get('store_id')

        if len(q) < 2:
            return Response({'results': []})

        from inventory.models import Product
        from django.db.models import Q

        qs = Product.objects.filter(
            is_active=True
        ).filter(
            Q(name__icontains=q) |
            Q(barcode__icontains=q) |
            Q(sku__icontains=q)
        ).select_related('category').order_by('name')[:10]

        store = None
        if store_id:
            try:
                from stores.models import Store
                store = Store.objects.get(pk=store_id)
            except Exception:
                pass

        results = []
        for p in qs:
            stock = None
            if store:
                try:
                    from inventory.models import Stock
                    stock = Stock.objects.get(product=p, store=store).quantity
                except Exception:
                    stock = 0
            results.append({
                **_serialize_product(p, store),
                'stock': stock,
            })

        return Response({'results': results})


# ------------------------------------------------------------------ #
#  1. Barcode Scan — resolve a barcode to product/bundle (DB only)    #
# ------------------------------------------------------------------ #

class BarcodeScanView(APIView):
    """
    POST /api/scan/barcode/

    Body: { "barcode": "IN0000000042", "store_id": 3, "mode": "receive_stock" }

    Resolves the barcode against the local DB only — no external HTTP calls.
    Response time is therefore bounded by DB latency alone (typically < 30 ms).

    Modes:
        product_lookup  — view product details
        receive_stock   — receive delivery (can add stock)
        pos_checkout    — POS (cashier — never creates products)
        stock_count     — count inventory
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        barcode_value = (request.data.get('barcode') or '').strip()
        store_id      = request.data.get('store_id')
        mode          = request.data.get('mode', 'product_lookup')
        session_id    = request.data.get('session_id')

        if not barcode_value:
            return Response(
                {'error': 'barcode is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        store = None
        if store_id:
            try:
                from stores.models import Store
                store = Store.objects.get(pk=store_id)
            except Exception:
                pass

        # DB-only resolution (no external API calls)
        from inventory.servicee.barcode_service import resolve_barcode
        resolution = resolve_barcode(barcode_value, store=store)

        payload = {
            'barcode': barcode_value,
            'found':   resolution['found'],
            'type':    resolution['type'],
            'message': resolution['message'],
            'mode':    mode,
            'actions': [],
            # external_lookup is intentionally omitted — DB-only policy
        }

        if resolution['found']:
            product = resolution['product']
            payload['product'] = _serialize_product(product, store)
            payload['stock']   = resolution.get('stock')

            if resolution['type'] == 'bundle':
                bundle = resolution['bundle']
                payload['bundle'] = {
                    'id':                  bundle.pk,
                    'child_product':       _serialize_product(bundle.child_product, store),
                    'child_qty':           bundle.child_qty,
                    'is_separate_product': bundle.is_separate_product,
                    'cost_per_unit':       str(bundle.effective_cost_per_unit),
                }

            if mode == 'receive_stock' and _can_receive_stock(request.user):
                payload['actions'] = ['add_stock']
            elif mode == 'pos_checkout':
                payload['actions'] = ['add_to_cart']
            elif mode == 'product_lookup':
                payload['actions'] = ['view_product', 'add_stock']
            elif mode == 'stock_count':
                payload['actions'] = ['record_count']

        else:
            # Product genuinely not in our DB
            if mode == 'pos_checkout':
                payload['message'] = (
                    'Product not found. Cannot be added at checkout. '
                    'Please check with the manager.'
                )
            else:
                if _can_create_products(request.user):
                    payload['actions'] = ['quick_create']
                else:
                    payload['message'] = (
                        'Product not found. Contact your stock manager to add it.'
                    )

        if session_id:
            _log_scan_event(
                session_id=session_id,
                barcode_value=barcode_value,
                resolution=resolution,
                outcome='product_found' if resolution['found'] else 'not_found',
            )

        return Response(payload, status=status.HTTP_200_OK)


def _serialize_product(product, store=None):
    """Minimal product dict for scan responses."""
    return {
        'id':               product.pk,
        'name':             product.name,
        'sku':              product.sku,
        'barcode':          product.barcode,
        'barcode_type':     getattr(product, 'barcode_type', 'manufacturer'),
        'selling_price':    str(product.selling_price),
        'cost_price':       str(product.cost_price),
        'unit_of_measure':  product.unit_of_measure,
        'category':         str(product.category) if product.category else None,
        'is_bundle':        getattr(product, 'is_bundle', False),
        'barcode_image_url': (
            product.barcode_image.url
            if getattr(product, 'barcode_image', None)
            else None
        ),
    }


def _log_scan_event(session_id, barcode_value, resolution, outcome, **kwargs):
    """Write a ScanEvent row (non-blocking, swallows errors)."""
    try:
        from inventory.models import ScanSession, ScanEvent
        session = ScanSession.objects.get(pk=session_id)
        ScanEvent.objects.create(
            session=session,
            barcode_scanned=barcode_value,
            product=resolution.get('product'),
            bundle=resolution.get('bundle'),
            outcome=outcome,
            was_bundle_scan=resolution.get('type') == 'bundle',
            **kwargs,
        )
        ScanSession.objects.filter(pk=session_id).update(
            total_scans=session.total_scans + 1,
            successful_scans=session.successful_scans + (1 if resolution['found'] else 0),
            failed_scans=session.failed_scans + (0 if resolution['found'] else 1),
        )
    except Exception as e:
        logger.warning(f"ScanEvent log failed: {e}")


# ------------------------------------------------------------------ #
#  2. Receive Stock                                                    #
# ------------------------------------------------------------------ #

class StockReceiveView(APIView):
    """
    POST /api/scan/receive-stock/

    Body:
    {
        "barcode": "IN0000000042",
        "store_id": 3,
        "quantity": 24,
        "cost_price": "1500.00",
        "notes": "Delivery note",
        "session_id": 12,
        "is_bundle_expand": false
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_receive_stock(request.user):
            return Response(
                {'error': 'You do not have permission to receive stock.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        barcode_value    = (request.data.get('barcode') or '').strip()
        store_id         = request.data.get('store_id')
        quantity         = request.data.get('quantity')
        cost_price       = request.data.get('cost_price')
        notes            = request.data.get('notes', '')
        session_id       = request.data.get('session_id')
        is_bundle_expand = request.data.get('is_bundle_expand', False)

        errors = {}
        if not barcode_value:
            errors['barcode'] = 'Required'
        if not store_id:
            errors['store_id'] = 'Required'
        if not quantity:
            errors['quantity'] = 'Required'
        else:
            try:
                quantity = Decimal(str(quantity))
                if quantity <= 0:
                    errors['quantity'] = 'Must be greater than 0'
            except Exception:
                errors['quantity'] = 'Invalid number'

        if errors:
            return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from stores.models import Store
            store = Store.objects.get(pk=store_id)
        except Exception:
            return Response(
                {'error': f'Store {store_id} not found'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from inventory.servicee.barcode_service import resolve_barcode
        resolution = resolve_barcode(barcode_value, store=store)

        if not resolution['found']:
            return Response(
                {'error': 'Product not found. Create it first.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            with transaction.atomic():
                result = _do_stock_receive(
                    resolution=resolution,
                    store=store,
                    quantity=quantity,
                    cost_price=cost_price,
                    notes=notes,
                    user=request.user,
                    is_bundle_expand=is_bundle_expand,
                )
        except Exception as e:
            logger.error(f"Stock receive error: {e}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if session_id:
            _log_scan_event(
                session_id=session_id,
                barcode_value=barcode_value,
                resolution=resolution,
                outcome='stock_added',
                quantity_added=result['quantity_added'],
            )

        return Response(result, status=status.HTTP_201_CREATED)


def _do_stock_receive(resolution, store, quantity, cost_price, notes, user, is_bundle_expand):
    from inventory.models import StockMovement

    product        = resolution['product']
    bundle         = resolution.get('bundle')
    actual_product = product
    actual_quantity = quantity
    bundle_note    = ''

    if bundle and not bundle.is_separate_product and is_bundle_expand:
        actual_product  = bundle.child_product
        actual_quantity = quantity * bundle.child_qty
        bundle_note     = (
            f" [Bundle expand: {quantity} × {bundle.parent_product.name} "
            f"= {actual_quantity} × {bundle.child_product.name}]"
        )

    if cost_price:
        effective_cost = Decimal(str(cost_price))
    elif bundle and not bundle.is_separate_product:
        effective_cost = bundle.effective_cost_per_unit
    else:
        effective_cost = actual_product.cost_price

    movement = StockMovement.objects.create(
        product=actual_product,
        store=store,
        movement_type='PURCHASE',
        quantity=actual_quantity,
        unit_cost=effective_cost,
        notes=f"{notes}{bundle_note}".strip(),
        created_by=user,
    )

    return {
        'success':        True,
        'product':        actual_product.name,
        'quantity_added': str(actual_quantity),
        'store':          store.name,
        'movement_id':    movement.pk,
        'message':        f"Added {actual_quantity} × {actual_product.name} to {store.name}",
    }


# ------------------------------------------------------------------ #
#  3. Quick Product Create                                             #
# ------------------------------------------------------------------ #

class QuickProductCreateView(APIView):
    """
    POST /api/scan/quick-create/

    Body:
    {
        "barcode": "5000112637922",
        "name": "Coca-Cola 300ml",
        "category_id": 5,
        "selling_price": "2000",
        "cost_price": "1500",
        "unit_of_measure": "PCE",
        "tax_rate": "A",
        "barcode_type": "manufacturer",
        "initial_stock": 24,
        "store_id": 3,
        "add_to_print_queue": true,
        "label_quantity": 50,
        "session_id": 12
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_create_products(request.user):
            return Response(
                {'error': 'You do not have permission to create products.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        data          = request.data
        barcode_value = (data.get('barcode') or '').strip()

        errors = {}
        for field in ['name', 'selling_price', 'cost_price', 'category_id']:
            if not data.get(field):
                errors[field] = 'Required'
        if not barcode_value:
            errors['barcode'] = 'Required'

        if errors:
            return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

        from inventory.models import Product
        if Product.objects.filter(barcode=barcode_value).exists():
            return Response(
                {'error': f'Barcode {barcode_value} is already assigned to another product.'},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            with transaction.atomic():
                product = _create_product_from_scan(data, barcode_value, request.user)
        except Exception as e:
            logger.error(f"Quick create error: {e}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if data.get('add_to_print_queue'):
            _queue_label_print(
                product=product,
                store_id=data.get('store_id'),
                quantity=int(data.get('label_quantity', 1)),
                user=request.user,
            )

        if data.get('session_id'):
            _log_scan_event(
                session_id=data['session_id'],
                barcode_value=barcode_value,
                resolution={'found': True, 'type': 'product', 'product': product, 'bundle': None},
                outcome='product_created',
            )

        return Response({
            'success': True,
            'product': _serialize_product(product),
            'message': f'Product "{product.name}" created successfully.',
        }, status=status.HTTP_201_CREATED)


def _create_product_from_scan(data, barcode_value, user):
    from inventory.models import Product, Category
    import re

    base          = re.sub(r'[^A-Z0-9]', '', data['name'].upper())[:8]
    sku_candidate = f"SC-{base}-{barcode_value[-4:]}"
    counter       = 1
    while Product.objects.filter(sku=sku_candidate).exists():
        sku_candidate = f"SC-{base}-{barcode_value[-4:]}-{counter}"
        counter += 1

    category = None
    if data.get('category_id'):
        category = Category.objects.filter(pk=data['category_id']).first()

    product = Product(
        name=data['name'],
        barcode=barcode_value,
        barcode_type=data.get('barcode_type', 'manufacturer'),
        sku=sku_candidate,
        category=category,
        selling_price=Decimal(str(data['selling_price'])),
        cost_price=Decimal(str(data['cost_price'])),
        unit_of_measure=data.get('unit_of_measure', 'PCE'),
        tax_rate=data.get('tax_rate', 'A'),
        description=data.get('description', ''),
        is_active=True,
    )
    product._skip_full_clean = False
    product.save()

    initial_stock = data.get('initial_stock')
    store_id      = data.get('store_id')
    if initial_stock and store_id:
        from stores.models import Store
        from inventory.models import StockMovement
        try:
            store = Store.objects.get(pk=store_id)
            StockMovement.objects.create(
                product=product,
                store=store,
                movement_type='PURCHASE',
                quantity=Decimal(str(initial_stock)),
                unit_cost=product.cost_price,
                notes='Initial stock via scan quick-create',
                created_by=user,
            )
        except Exception as e:
            logger.warning(f"Initial stock creation failed for {product.pk}: {e}")

    return product


def _queue_label_print(product, store_id, quantity, user):
    try:
        from inventory.models import BarcodeLabel
        store = None
        if store_id:
            from stores.models import Store
            store = Store.objects.filter(pk=store_id).first()
        BarcodeLabel.objects.create(
            product=product,
            store=store,
            quantity=quantity,
            requested_by=user,
        )
    except Exception as e:
        logger.warning(f"Label queue failed: {e}")


# ------------------------------------------------------------------ #
#  4. Scan Session management                                          #
# ------------------------------------------------------------------ #

class ScanSessionView(APIView):
    """
    POST  /api/scan/session/              — start a new session
    PATCH /api/scan/session/<pk>/complete/ — complete a session
    GET   /api/scan/session/<pk>/         — get session summary
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        mode     = request.data.get('mode', 'receive_stock')
        store_id = request.data.get('store_id')

        store = None
        if store_id:
            from stores.models import Store
            store = Store.objects.filter(pk=store_id).first()

        from inventory.models import ScanSession
        session = ScanSession.objects.create(
            user=request.user,
            store=store,
            mode=mode,
        )
        return Response({
            'session_id': session.pk,
            'mode':       mode,
            'store':      store.name if store else None,
            'started_at': session.started_at,
        }, status=status.HTTP_201_CREATED)

    def patch(self, request, pk=None):
        from inventory.models import ScanSession
        try:
            session = ScanSession.objects.get(pk=pk, user=request.user)
        except ScanSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=404)

        session.complete()
        return Response({
            'session_id':          session.pk,
            'total_scans':         session.total_scans,
            'successful_scans':    session.successful_scans,
            'new_products_created': session.new_products_created,
            'duration':            str(session.duration),
        })

    def get(self, request, pk=None):
        from inventory.models import ScanSession, ScanEvent
        try:
            session = ScanSession.objects.get(pk=pk, user=request.user)
        except ScanSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=404)

        events = ScanEvent.objects.filter(session=session).order_by('-scanned_at')
        return Response({
            'session_id':          session.pk,
            'mode':                session.mode,
            'store':               session.store.name if session.store else None,
            'status':              session.status,
            'total_scans':         session.total_scans,
            'successful_scans':    session.successful_scans,
            'failed_scans':        session.failed_scans,
            'new_products_created': session.new_products_created,
            'events': [
                {
                    'barcode':    e.barcode_scanned,
                    'product':    e.product.name if e.product else None,
                    'outcome':    e.outcome,
                    'qty':        str(e.quantity_added) if e.quantity_added else None,
                    'scanned_at': e.scanned_at,
                }
                for e in events[:50]
            ],
        })


# ------------------------------------------------------------------ #
#  5. Barcode Label queue                                              #
# ------------------------------------------------------------------ #

class BarcodeLabelView(APIView):
    """
    GET  /api/scan/labels/ — list pending labels
    POST /api/scan/labels/ — add products to print queue
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_print_labels(request.user):
            return Response({'error': 'Permission denied'}, status=403)

        from inventory.models import BarcodeLabel
        pending = BarcodeLabel.objects.filter(
            status='pending'
        ).select_related('product', 'store').order_by('-created_at')

        return Response({
            'count': pending.count(),
            'labels': [
                {
                    'id':           lb.pk,
                    'product':      lb.product.name,
                    'barcode':      lb.product.barcode,
                    'quantity':     lb.quantity,
                    'size':         lb.label_size,
                    'include_price': lb.include_price,
                    'store':        lb.store.name if lb.store else None,
                    'requested_by': str(lb.requested_by) if lb.requested_by else None,
                    'created_at':   lb.created_at,
                }
                for lb in pending
            ],
        })

    def post(self, request):
        if not _can_print_labels(request.user):
            return Response({'error': 'Permission denied'}, status=403)

        product_ids   = request.data.get('product_ids', [])
        quantity      = int(request.data.get('quantity', 1))
        size          = request.data.get('size', 'medium')
        include_price = request.data.get('include_price', True)
        store_id      = request.data.get('store_id')

        from inventory.models import Product, BarcodeLabel

        store = None
        if store_id:
            from stores.models import Store
            store = Store.objects.filter(pk=store_id).first()

        created = []
        for pid in product_ids:
            product = Product.objects.filter(pk=pid).first()
            if product:
                lb = BarcodeLabel.objects.create(
                    product=product,
                    store=store,
                    quantity=quantity,
                    label_size=size,
                    include_price=include_price,
                    requested_by=request.user,
                )
                created.append(lb.pk)

        return Response({
            'created':   len(created),
            'label_ids': created,
            'message':   f'{len(created)} label job(s) queued for printing.',
        }, status=status.HTTP_201_CREATED)