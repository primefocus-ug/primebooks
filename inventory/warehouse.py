from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, F, Q, Count, Case, When, DecimalField,Avg
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from datetime import timedelta
import json

from .models import (
    StockStoreInventory,
    StockTransferRequest, StockTransferItem,
    StockStoreMovement, Stock, Product
)
from stores.models import StockStore
from .forms import (
    StockStoreForm, StockTransferRequestForm,
    StockTransferItemFormSet, ReceiveTransferForm
)


# ==================== STOCKSTORE VIEWS ====================

@login_required
def stockstore_list(request):
    """List all warehouses/stockstores"""
    stockstores = StockStore.objects.filter(
        company=request.tenant,
        is_active=True
    ).annotate(
        total_inventory=Count('inventory_items'),
        low_stock_count=Count(
            Case(
                When(
                    inventory_items__quantity__lte=F('inventory_items__low_stock_threshold'),
                    then=1
                )
            )
        )
    ).order_by('-is_main_stockstore', 'name')

    context = {
        'stockstores': stockstores,
        'page_title': 'Warehouses & Stock Stores'
    }
    return render(request, 'inventory/stockstore_list.html', context)


@login_required
def stockstore_detail(request, pk):
    """Detailed view of a specific warehouse"""
    stockstore = get_object_or_404(
        StockStore.objects.select_related('company'),
        pk=pk,
        company=request.tenant
    )

    # Get inventory summary
    inventory = StockStoreInventory.objects.filter(
        stockstore=stockstore
    ).select_related('product', 'product__category')

    # Filter inventory
    search = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')

    if search:
        inventory = inventory.filter(
            Q(product__name__icontains=search) |
            Q(product__sku__icontains=search)
        )

    if status_filter == 'low':
        inventory = inventory.filter(quantity__lte=F('low_stock_threshold'))
    elif status_filter == 'out':
        inventory = inventory.filter(quantity=0)

    # Pagination
    paginator = Paginator(inventory, 50)
    page_number = request.GET.get('page')
    inventory_page = paginator.get_page(page_number)

    # Summary stats
    summary = stockstore.get_inventory_summary()

    # Recent movements
    recent_movements = StockStoreMovement.objects.filter(
        stockstore=stockstore
    ).select_related('product', 'created_by').order_by('-created_at')[:10]

    # Pending transfers
    pending_outgoing = StockTransferRequest.objects.filter(
        source_stockstore=stockstore,
        status__in=['PENDING', 'APPROVED', 'IN_TRANSIT']
    ).count()

    pending_incoming = StockTransferRequest.objects.filter(
        destination_stockstore=stockstore,
        status='IN_TRANSIT'
    ).count()

    context = {
        'stockstore': stockstore,
        'inventory': inventory_page,
        'summary': summary,
        'recent_movements': recent_movements,
        'pending_outgoing': pending_outgoing,
        'pending_incoming': pending_incoming,
        'search': search,
        'status_filter': status_filter,
        'page_title': f'Warehouse: {stockstore.name}'
    }
    return render(request, 'inventory/stockstore_detail.html', context)


@login_required
def stockstore_create(request):
    """Create new warehouse"""
    if request.method == 'POST':
        form = StockStoreForm(request.POST)
        if form.is_valid():
            stockstore = form.save(commit=False)
            stockstore.company = request.tenant
            stockstore.created_by = request.user
            stockstore.save()
            form.save_m2m()  # Save many-to-many relationships

            messages.success(request, f'Warehouse "{stockstore.name}" created successfully!')
            return redirect('inventory:stockstore_detail', pk=stockstore.pk)
    else:
        form = StockStoreForm()

    context = {
        'form': form,
        'page_title': 'Create New Warehouse'
    }
    return render(request, 'inventory/stockstore_form.html', context)


@login_required
def stockstore_inventory_add(request, stockstore_id):
    """Add product to warehouse inventory"""
    stockstore = get_object_or_404(StockStore, pk=stockstore_id, company=request.tenant)

    if request.method == 'POST':
        product_id = request.POST.get('product')
        quantity = request.POST.get('quantity')
        reference = request.POST.get('reference', '')
        notes = request.POST.get('notes', '')

        try:
            product = Product.objects.get(pk=product_id)
            quantity = float(quantity)

            # Get or create inventory record
            inventory, created = StockStoreInventory.objects.get_or_create(
                stockstore=stockstore,
                product=product,
                defaults={'quantity': 0}
            )

            # Add stock
            inventory.add_stock(quantity)

            # Create movement record
            StockStoreMovement.objects.create(
                stockstore=stockstore,
                product=product,
                movement_type='PURCHASE',
                quantity=quantity,
                reference=reference,
                notes=notes,
                created_by=request.user
            )

            messages.success(
                request,
                f'Added {quantity} units of {product.name} to {stockstore.name}'
            )

        except Exception as e:
            messages.error(request, f'Error adding inventory: {str(e)}')

        return redirect('inventory:stockstore_detail', pk=stockstore_id)

    # GET request - show form
    products = Product.objects.filter(is_active=True).order_by('name')

    context = {
        'stockstore': stockstore,
        'products': products,
        'page_title': f'Add Inventory to {stockstore.name}'
    }
    return render(request, 'inventory/stockstore_add_inventory.html', context)


# ==================== TRANSFER VIEWS ====================

@login_required
def transfer_list(request):
    """List all transfer requests"""
    # Filter options
    status_filter = request.GET.get('status', '')
    transfer_type = request.GET.get('type', '')
    search = request.GET.get('search', '')

    transfers = StockTransferRequest.objects.filter(
        Q(source_stockstore__company=request.tenant) |
        Q(destination_stockstore__company=request.tenant) |
        Q(source_store__company=request.tenant) |
        Q(destination_store__company=request.tenant)
    ).select_related(
        'source_stockstore', 'destination_stockstore',
        'source_store', 'destination_store',
        'requested_by', 'approved_by'
    ).distinct()

    if status_filter:
        transfers = transfers.filter(status=status_filter)

    if transfer_type:
        transfers = transfers.filter(transfer_type=transfer_type)

    if search:
        transfers = transfers.filter(
            Q(transfer_number__icontains=search) |
            Q(reason__icontains=search)
        )

    # FIXED: Use primary_role instead of role attribute
    primary_role = request.user.primary_role
    if primary_role and primary_role.group.name == 'CASHIER':
        # Cashiers see transfers for their stores
        user_stores = request.user.stores.all()
        transfers = transfers.filter(
            Q(source_store__in=user_stores) |
            Q(destination_store__in=user_stores)
        )

    transfers = transfers.order_by('-created_at')

    # Pagination
    paginator = Paginator(transfers, 25)
    page_number = request.GET.get('page')
    transfers_page = paginator.get_page(page_number)

    # Summary stats
    summary = {
        'total': transfers.count(),
        'pending': transfers.filter(status='PENDING').count(),
        'approved': transfers.filter(status='APPROVED').count(),
        'in_transit': transfers.filter(status='IN_TRANSIT').count(),
        'completed': transfers.filter(status='COMPLETED').count(),
    }

    context = {
        'transfers': transfers_page,
        'summary': summary,
        'status_filter': status_filter,
        'transfer_type': transfer_type,
        'search': search,
        'page_title': 'Stock Transfers'
    }
    return render(request, 'inventory/transfer_list.html', context)

@login_required
def transfer_detail(request, pk):
    """Detailed view of a transfer request"""
    transfer = get_object_or_404(
        StockTransferRequest.objects.select_related(
            'source_stockstore', 'destination_stockstore',
            'source_store', 'destination_store',
            'requested_by', 'approved_by', 'dispatched_by', 'received_by'
        ),
        pk=pk
    )

    items = transfer.items.select_related('product').all()

    # Check permissions for actions
    can_approve = (
            request.user.role in ['ADMIN', 'MANAGER'] and
            transfer.can_be_approved
    )

    can_dispatch = (
            transfer.can_be_dispatched and
            (request.user in transfer.source_stockstore.managers.all() if transfer.source_stockstore
             else request.user in transfer.source_store.store_managers.all())
    )

    can_receive = (
            transfer.can_be_received and
            (request.user in transfer.destination_stockstore.managers.all() if transfer.destination_stockstore
             else request.user in transfer.destination_store.store_managers.all())
    )

    context = {
        'transfer': transfer,
        'items': items,
        'can_approve': can_approve,
        'can_dispatch': can_dispatch,
        'can_receive': can_receive,
        'page_title': f'Transfer: {transfer.transfer_number}'
    }
    return render(request, 'inventory/transfer_detail.html', context)


@login_required
def transfer_create(request):
    """Create new transfer request"""
    if request.method == 'POST':
        form = StockTransferRequestForm(request.POST, user=request.user, company=request.tenant)
        formset = StockTransferItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            transfer = form.save(commit=False)
            transfer.requested_by = request.user
            transfer.save()

            # Save items
            items = formset.save(commit=False)
            for item in items:
                item.transfer = transfer
                item.save()

            # Auto-submit if specified
            if request.POST.get('submit_for_approval'):
                try:
                    transfer.submit_for_approval()
                    messages.success(
                        request,
                        f'Transfer {transfer.transfer_number} created and submitted for approval!'
                    )
                except ValueError as e:
                    messages.warning(request, str(e))
            else:
                messages.success(
                    request,
                    f'Transfer {transfer.transfer_number} created as draft!'
                )

            return redirect('inventory:transfer_detail', pk=transfer.pk)
    else:
        form = StockTransferRequestForm(user=request.user, company=request.tenant)
        formset = StockTransferItemFormSet()

    # Get products with stock info for reference
    products = Product.objects.filter(is_active=True).select_related('category')

    context = {
        'form': form,
        'formset': formset,
        'products': products,
        'page_title': 'Create Stock Transfer'
    }
    return render(request, 'inventory/transfer_form.html', context)


@login_required
def transfer_create_from_sale(request, sale_id):
    """Create transfer request to fulfill a sale (when branch is out of stock)"""
    from sales.models import Sale, SaleItem

    sale = get_object_or_404(Sale, pk=sale_id)

    # Find which items are out of stock
    out_of_stock_items = []
    for item in sale.items.all():
        stock = Stock.objects.filter(
            store=sale.store,
            product=item.product
        ).first()

        if not stock or stock.quantity < item.quantity:
            available = stock.quantity if stock else 0
            needed = item.quantity - available

            # Check if available in warehouse
            warehouse_stock = StockStoreInventory.objects.filter(
                product=item.product,
                quantity__gte=needed
            ).first()

            if warehouse_stock:
                out_of_stock_items.append({
                    'product': item.product,
                    'needed': needed,
                    'available': available,
                    'warehouse': warehouse_stock.stockstore,
                    'warehouse_available': warehouse_stock.available_quantity
                })

    if request.method == 'POST':
        warehouse_id = request.POST.get('source_stockstore')
        warehouse = get_object_or_404(StockStore, pk=warehouse_id)

        # Create transfer
        transfer = StockTransferRequest.objects.create(
            transfer_type='WAREHOUSE_TO_BRANCH',
            source_stockstore=warehouse,
            destination_store=sale.store,
            requested_by=request.user,
            reason=f"Fulfill sale #{sale.invoice_number}",
            priority='URGENT',
            related_sale=sale
        )

        # Add items
        for item_data in out_of_stock_items:
            StockTransferItem.objects.create(
                transfer=transfer,
                product=item_data['product'],
                quantity_requested=item_data['needed']
            )

        # Submit for approval
        transfer.submit_for_approval()

        messages.success(
            request,
            f'Transfer request {transfer.transfer_number} created to fulfill sale!'
        )
        return redirect('inventory:transfer_detail', pk=transfer.pk)

    context = {
        'sale': sale,
        'out_of_stock_items': out_of_stock_items,
        'page_title': f'Create Transfer for Sale #{sale.invoice_number}'
    }
    return render(request, 'inventory/transfer_from_sale.html', context)


@login_required
@require_POST
def transfer_approve(request, pk):
    """Approve a transfer request"""
    transfer = get_object_or_404(StockTransferRequest, pk=pk)

    if not request.user.role in ['ADMIN', 'MANAGER']:
        messages.error(request, 'You do not have permission to approve transfers')
        return redirect('inventory:transfer_detail', pk=pk)

    try:
        notes = request.POST.get('approval_notes', '')
        transfer.approve(approved_by=request.user, notes=notes)
        messages.success(request, f'Transfer {transfer.transfer_number} approved successfully!')
    except ValueError as e:
        messages.error(request, f'Error approving transfer: {str(e)}')

    return redirect('inventory:transfer_detail', pk=pk)


@login_required
@require_POST
def transfer_reject(request, pk):
    """Reject a transfer request"""
    transfer = get_object_or_404(StockTransferRequest, pk=pk)

    if not request.user.role in ['ADMIN', 'MANAGER']:
        messages.error(request, 'You do not have permission to reject transfers')
        return redirect('inventory:transfer_detail', pk=pk)

    reason = request.POST.get('rejection_reason', '')
    if not reason:
        messages.error(request, 'Please provide a reason for rejection')
        return redirect('inventory:transfer_detail', pk=pk)

    try:
        transfer.reject(rejected_by=request.user, reason=reason)
        messages.warning(request, f'Transfer {transfer.transfer_number} rejected')
    except ValueError as e:
        messages.error(request, f'Error rejecting transfer: {str(e)}')

    return redirect('inventory:transfer_detail', pk=pk)


@login_required
@require_POST
def transfer_dispatch(request, pk):
    """Dispatch an approved transfer"""
    transfer = get_object_or_404(StockTransferRequest, pk=pk)

    try:
        notes = request.POST.get('dispatch_notes', '')
        transfer.dispatch(dispatched_by=request.user, notes=notes)
        messages.success(request, f'Transfer {transfer.transfer_number} dispatched successfully!')
    except ValueError as e:
        messages.error(request, f'Error dispatching transfer: {str(e)}')

    return redirect('inventory:transfer_detail', pk=pk)


@login_required
def transfer_receive(request, pk):
    """Receive a transfer at destination"""
    transfer = get_object_or_404(StockTransferRequest, pk=pk)

    if request.method == 'POST':
        form = ReceiveTransferForm(request.POST, transfer=transfer)

        if form.is_valid():
            try:
                actual_quantities = form.cleaned_data['actual_quantities']
                notes = form.cleaned_data['receipt_notes']

                transfer.receive(
                    received_by=request.user,
                    actual_quantities=actual_quantities,
                    notes=notes
                )

                messages.success(
                    request,
                    f'Transfer {transfer.transfer_number} received successfully!'
                )
                return redirect('inventory:transfer_detail', pk=pk)

            except ValueError as e:
                messages.error(request, f'Error receiving transfer: {str(e)}')
    else:
        form = ReceiveTransferForm(transfer=transfer)

    context = {
        'transfer': transfer,
        'form': form,
        'page_title': f'Receive Transfer: {transfer.transfer_number}'
    }
    return render(request, 'inventory/transfer_receive.html', context)


@login_required
@require_POST
def transfer_cancel(request, pk):
    """Cancel a transfer request"""
    transfer = get_object_or_404(StockTransferRequest, pk=pk)

    reason = request.POST.get('cancellation_reason', '')
    if not reason:
        messages.error(request, 'Please provide a reason for cancellation')
        return redirect('inventory:transfer_detail', pk=pk)

    try:
        transfer.cancel(cancelled_by=request.user, reason=reason)
        messages.warning(request, f'Transfer {transfer.transfer_number} cancelled')
    except ValueError as e:
        messages.error(request, f'Error cancelling transfer: {str(e)}')

    return redirect('inventory:transfer_detail', pk=pk)


# ==================== AJAX/API VIEWS ====================

@login_required
def check_product_availability(request):
    """AJAX: Check product availability across locations"""
    product_id = request.GET.get('product_id')
    quantity = float(request.GET.get('quantity', 0))

    if not product_id:
        return JsonResponse({'error': 'Product ID required'}, status=400)

    product = get_object_or_404(Product, pk=product_id)

    # Check warehouses
    warehouse_stock = StockStoreInventory.objects.filter(
        product=product,
        stockstore__company=request.tenant,
        stockstore__is_active=True
    ).select_related('stockstore').values(
        'stockstore__id',
        'stockstore__name',
        'quantity',
        'reserved_quantity'
    )

    warehouses = []
    for stock in warehouse_stock:
        available = stock['quantity'] - stock['reserved_quantity']
        warehouses.append({
            'id': stock['stockstore__id'],
            'name': stock['stockstore__name'],
            'quantity': float(stock['quantity']),
            'available': float(available),
            'can_fulfill': available >= quantity
        })

    # Check branches
    branch_stock = Stock.objects.filter(
        product=product,
        store__company=request.tenant,
        store__is_active=True
    ).select_related('store').values(
        'store__id',
        'store__name',
        'quantity'
    )

    branches = []
    for stock in branch_stock:
        branches.append({
            'id': stock['store__id'],
            'name': stock['store__name'],
            'quantity': float(stock['quantity']),
            'can_fulfill': stock['quantity'] >= quantity
        })

    return JsonResponse({
        'product': {
            'id': product.id,
            'name': product.name,
            'sku': product.sku
        },
        'requested_quantity': quantity,
        'warehouses': warehouses,
        'branches': branches,
        'total_available': sum(w['available'] for w in warehouses) + sum(b['quantity'] for b in branches)
    })


@login_required
def get_warehouse_inventory(request, stockstore_id):
    """AJAX: Get inventory for a specific warehouse"""
    stockstore = get_object_or_404(StockStore, pk=stockstore_id, company=request.tenant)

    inventory = StockStoreInventory.objects.filter(
        stockstore=stockstore,
        quantity__gt=0
    ).select_related('product').values(
        'product__id',
        'product__name',
        'product__sku',
        'quantity',
        'reserved_quantity'
    )

    items = []
    for item in inventory:
        items.append({
            'product_id': item['product__id'],
            'product_name': item['product__name'],
            'sku': item['product__sku'],
            'quantity': float(item['quantity']),
            'reserved': float(item['reserved_quantity']),
            'available': float(item['quantity'] - item['reserved_quantity'])
        })

    return JsonResponse({'items': items})


# ==================== REPORTING VIEWS ====================

@login_required
def inventory_report(request):
    """Comprehensive inventory report across all locations"""

    # Date filters
    date_from = request.GET.get('date_from', (timezone.now() - timedelta(days=30)).date())
    date_to = request.GET.get('date_to', timezone.now().date())

    # Warehouse inventory summary
    warehouse_summary = StockStoreInventory.objects.filter(
        stockstore__company=request.tenant
    ).values(
        'stockstore__name'
    ).annotate(
        total_products=Count('id'),
        total_quantity=Sum('quantity'),
        total_value=Sum(F('quantity') * F('product__cost_price')),
        low_stock=Count(Case(
            When(quantity__lte=F('low_stock_threshold'), then=1)
        ))
    ).order_by('stockstore__name')

    # Branch inventory summary
    branch_summary = Stock.objects.filter(
        store__company=request.tenant
    ).values(
        'store__name'
    ).annotate(
        total_products=Count('id'),
        total_quantity=Sum('quantity'),
        total_value=Sum(F('quantity') * F('product__cost_price')),
        low_stock=Count(Case(
            When(quantity__lte=F('low_stock_threshold'), then=1)
        ))
    ).order_by('store__name')

    # Transfer statistics
    transfer_stats = StockTransferRequest.objects.filter(
        created_at__date__range=[date_from, date_to]
    ).aggregate(
        total_transfers=Count('id'),
        completed=Count(Case(When(status='COMPLETED', then=1))),
        pending=Count(Case(When(status='PENDING', then=1))),
        in_transit=Count(Case(When(status='IN_TRANSIT', then=1))),
        cancelled=Count(Case(When(status='CANCELLED', then=1)))
    )

    # Top transferred products
    top_products = StockTransferItem.objects.filter(
        transfer__created_at__date__range=[date_from, date_to],
        transfer__status='COMPLETED'
    ).values(
        'product__name',
        'product__sku'
    ).annotate(
        total_quantity=Sum('quantity_received')
    ).order_by('-total_quantity')[:10]

    # Movement trends
    movement_trends = StockStoreMovement.objects.filter(
        created_at__date__range=[date_from, date_to]
    ).values(
        'movement_type'
    ).annotate(
        count=Count('id'),
        total_quantity=Sum('quantity')
    )

    context = {
        'warehouse_summary': warehouse_summary,
        'branch_summary': branch_summary,
        'transfer_stats': transfer_stats,
        'top_products': top_products,
        'movement_trends': movement_trends,
        'date_from': date_from,
        'date_to': date_to,
        'page_title': 'Inventory Report'
    }
    return render(request, 'inventory/inventory_report.html', context)


@login_required
def transfer_report(request):
    """Transfer activity report"""

    date_from = request.GET.get('date_from', (timezone.now() - timedelta(days=30)).date())
    date_to = request.GET.get('date_to', timezone.now().date())

    # Transfer summary by type
    by_type = StockTransferRequest.objects.filter(
        created_at__date__range=[date_from, date_to]
    ).values('transfer_type').annotate(
        count=Count('id'),
        completed=Count(Case(When(status='COMPLETED', then=1))),
        avg_completion_time=Avg(
            F('received_at') - F('created_at'),
            output_field=DecimalField()
        )
    )

    # Transfer summary by status
    by_status = StockTransferRequest.objects.filter(
        created_at__date__range=[date_from, date_to]
    ).values('status').annotate(count=Count('id'))

    # Daily transfer volume
    daily_volume = StockTransferRequest.objects.filter(
        created_at__date__range=[date_from, date_to]
    ).extra(
        select={'day': 'date(created_at)'}
    ).values('day').annotate(
        count=Count('id'),
        completed=Count(Case(When(status='COMPLETED', then=1)))
    ).order_by('day')

    # Warehouse performance
    warehouse_performance = StockTransferRequest.objects.filter(
        created_at__date__range=[date_from, date_to],
        source_stockstore__isnull=False
    ).values(
        'source_stockstore__name'
    ).annotate(
        total_transfers=Count('id'),
        completed=Count(Case(When(status='COMPLETED', then=1))),
        avg_items=Avg('items__quantity_sent')
    ).order_by('-total_transfers')

    # Branch receiving performance
    branch_performance = StockTransferRequest.objects.filter(
        created_at__date__range=[date_from, date_to],
        destination_store__isnull=False
    ).values(
        'destination_store__name'
    ).annotate(
        total_received=Count(Case(When(status='COMPLETED', then=1))),
        total_requested=Count('id')
    ).order_by('-total_received')

    context = {
        'by_type': by_type,
        'by_status': by_status,
        'daily_volume': daily_volume,
        'warehouse_performance': warehouse_performance,
        'branch_performance': branch_performance,
        'date_from': date_from,
        'date_to': date_to,
        'page_title': 'Transfer Activity Report'
    }
    return render(request, 'inventory/transfer_report.html', context)


@login_required
def stock_movement_report(request):
    """Stock movement report for warehouses"""

    date_from = request.GET.get('date_from', (timezone.now() - timedelta(days=30)).date())
    date_to = request.GET.get('date_to', timezone.now().date())
    stockstore_id = request.GET.get('stockstore')

    movements = StockStoreMovement.objects.filter(
        created_at__date__range=[date_from, date_to]
    ).select_related('stockstore', 'product', 'created_by')

    if stockstore_id:
        movements = movements.filter(stockstore_id=stockstore_id)

    # Summary by movement type
    by_type = movements.values('movement_type').annotate(
        count=Count('id'),
        total_quantity=Sum('quantity')
    )

    # Summary by warehouse
    by_warehouse = movements.values(
        'stockstore__name'
    ).annotate(
        count=Count('id'),
        inbound=Sum(Case(
            When(quantity__gt=0, then='quantity'),
            default=0
        )),
        outbound=Sum(Case(
            When(quantity__lt=0, then='quantity'),
            default=0
        ))
    ).order_by('stockstore__name')

    # Top products by movement
    top_products = movements.values(
        'product__name',
        'product__sku'
    ).annotate(
        movement_count=Count('id'),
        total_quantity=Sum('quantity')
    ).order_by('-movement_count')[:20]

    # Paginate movements
    paginator = Paginator(movements.order_by('-created_at'), 50)
    page_number = request.GET.get('page')
    movements_page = paginator.get_page(page_number)

    # Get all warehouses for filter
    stockstores = StockStore.objects.filter(
        company=request.tenant,
        is_active=True
    )

    context = {
        'movements': movements_page,
        'by_type': by_type,
        'by_warehouse': by_warehouse,
        'top_products': top_products,
        'stockstores': stockstores,
        'selected_stockstore': stockstore_id,
        'date_from': date_from,
        'date_to': date_to,
        'page_title': 'Stock Movement Report'
    }
    return render(request, 'inventory/stock_movement_report.html', context)


@login_required
def low_stock_alert_report(request):
    """Report of low stock items across all locations"""

    # Warehouse low stock
    warehouse_low_stock = StockStoreInventory.objects.filter(
        stockstore__company=request.tenant,
        quantity__lte=F('low_stock_threshold')
    ).select_related('stockstore', 'product').order_by('quantity')

    # Branch low stock
    branch_low_stock = Stock.objects.filter(
        store__company=request.tenant,
        quantity__lte=F('low_stock_threshold')
    ).select_related('store', 'product').order_by('quantity')

    # Out of stock in warehouses
    warehouse_out = StockStoreInventory.objects.filter(
        stockstore__company=request.tenant,
        quantity=0
    ).select_related('stockstore', 'product')

    # Out of stock in branches
    branch_out = Stock.objects.filter(
        store__company=request.tenant,
        quantity=0
    ).select_related('store', 'product')

    context = {
        'warehouse_low_stock': warehouse_low_stock,
        'branch_low_stock': branch_low_stock,
        'warehouse_out': warehouse_out,
        'branch_out': branch_out,
        'page_title': 'Low Stock Alerts'
    }
    return render(request, 'inventory/low_stock_report.html', context)