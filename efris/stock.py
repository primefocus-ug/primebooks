from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db.models import Q
from inventory.models import Product, Stock, StockMovement
from stores.models import Store
from .services import EnhancedEFRISAPIClient


@login_required
def stock_management_dashboard(request):
    """Stock management dashboard with EFRIS sync status"""
    company = request.tenant

    # Get statistics
    total_products = Product.objects.filter(
        efris_is_uploaded=True
    ).count()

    stocks_needing_sync = Stock.objects.filter(
        product__efris_is_uploaded=True,
        efris_sync_required=True
    ).count()

    recent_movements = StockMovement.objects.all().order_by('-created_at')[:10]

    # ✅ ADD THIS: Get actual products for the dropdowns
    products = Product.objects.filter(
        efris_is_uploaded=True,
        is_active=True
    ).order_by('name')

    context = {
        'total_products': total_products,
        'stocks_needing_sync': stocks_needing_sync,
        'recent_movements': recent_movements,
        'products': products,  # ✅ Add the products queryset
    }

    return render(request, 'efris/stock_management_dashboard.html', context)

from django.http import JsonResponse

@login_required
def stock_query_by_product(request, product_id):
    company = request.tenant
    product = get_object_or_404(Product, id=product_id)

    if not product.efris_goods_id:
        return JsonResponse({'error': f'Product {product.name} has not been uploaded to EFRIS yet.'}, status=400)

    if request.method == 'POST':
        branch_id = request.POST.get('branch_id')
        try:
            client = EnhancedEFRISAPIClient(company)
            auth_result = client.ensure_authenticated()
            if not auth_result.get("success"):
                return JsonResponse({'error': 'EFRIS authentication failed'}, status=401)

            result = client.t128_query_stock_by_goods_id(product.efris_goods_id, branch_id=branch_id)

            if result:
                return JsonResponse({'success': True, 'data': result})
            else:
                return JsonResponse({'success': False, 'message': 'No stock information found.'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    stores = Store.objects.filter(company=company)
    return render(request, 'efris/stock_query.html', {'product': product, 'stores': stores})



@login_required
@require_http_methods(["GET", "POST"])
def stock_increase(request, product_id):
    """Increase stock for a product in EFRIS (T131 - Operation 101)"""
    company = request.tenant
    product = get_object_or_404(Product, id=product_id)

    # ✅ Handle GET — just show the form page
    if request.method == "GET":
        stores = Store.objects.all()
        stock_in_types = [
            ('101', 'Purchase'),
            ('102', 'Local Purchase'),
            ('103', 'Manufacture/Assembling'),
            ('104', 'Return'),
        ]
        return render(request, "efris/stock_increase.html", {
            "product": product,
            "stores": stores,
            "stock_in_types": stock_in_types,
        })

    # ✅ Handle POST — actually increase stock in EFRIS
    try:
        quantity = float(request.POST.get('quantity', 0))
        unit_price = float(request.POST.get('unit_price', product.cost_price or 0))
        supplier_name = request.POST.get('supplier_name', '')
        supplier_tin = request.POST.get('supplier_tin', '')
        stock_in_type = request.POST.get('stock_in_type', '102')
        invoice_no = request.POST.get('invoice_no', '')

        if quantity <= 0:
            messages.error(request, 'Quantity must be greater than zero')
            return redirect(request.path)

        client = EnhancedEFRISAPIClient(company)
        store = get_object_or_404(Store, id=request.POST.get('store_id'))

        result = client.increase_stock_from_product(
            product=product,
            quantity=quantity,
            store=store,
            stock_in_type=stock_in_type,
            supplier_name=supplier_name or (
                product.supplier.name if hasattr(product, 'supplier') and product.supplier else 'Internal'),
            supplier_tin=supplier_tin or (
                product.supplier.tin if hasattr(product, 'supplier') and product.supplier else None),
            invoice_no=invoice_no
        )

        if result and isinstance(result, list) and len(result) > 0:
            first_result = result[0]
            return_code = first_result.get('returnCode', '99')

            if return_code in ['00', '601']:
                messages.success(request, f"✓ Stock increased for '{product.name}': +{quantity} units")
            else:
                messages.error(request, f"❌ EFRIS error: {first_result.get('returnMessage', 'Unknown error')}")
        else:
            messages.error(request, "❌ No response received from EFRIS")

    except Exception as e:
        messages.error(request, f"❌ Unexpected error: {str(e)}")

    return redirect('efris:stock_management_dashboard')


@login_required
def stock_decrease(request, product_id):
    """Decrease stock in EFRIS (T131 - Operation Type 102)"""
    company = request.tenant
    product = get_object_or_404(Product, id=product_id)

    if not product.efris_goods_id:
        messages.error(request, f'Product {product.name} must be uploaded to EFRIS first')
        return redirect('efris:stock_management_dashboard')

    stores = Store.objects.filter(company=company)

    if request.method == 'POST':
        try:
            quantity = float(request.POST.get('quantity', 0))
            store_id = request.POST.get('store_id')
            adjust_type = request.POST.get('adjust_type', '105')  # Default: Raw Materials
            remarks = request.POST.get('remarks', '')

            if quantity <= 0:
                messages.error(request, 'Quantity must be greater than 0')
                return redirect('efris:stock_decrease', product_id=product_id)

            store = get_object_or_404(Store, id=store_id, company=company)

            # Check if we have enough stock locally
            try:
                stock = Stock.objects.get(product=product, store=store)
                if stock.quantity < quantity:
                    messages.warning(
                        request,
                        f'Local stock ({stock.quantity}) is less than requested decrease ({quantity})'
                    )
            except Stock.DoesNotExist:
                messages.warning(request, 'No local stock record found for this product in this store')

            # Validate remarks for adjust_type=104 (Others)
            if adjust_type == '104' and not remarks:
                messages.error(request, 'Remarks are required for adjust type "Others"')
                return redirect('efris:stock_decrease', product_id=product_id)

            client = EnhancedEFRISAPIClient(company)
            auth_result = client.ensure_authenticated()
            if not auth_result.get("success"):
                messages.error(request, f"EFRIS authentication failed: {auth_result.get('error')}")
                return redirect('efris:stock_decrease', product_id=product_id)
            result = client.decrease_stock_from_product(
                product=product,
                quantity=quantity,
                store=store,
                adjust_type=adjust_type,
                remarks=remarks or f'Stock adjustment for {product.name}'
            )

            if result and result[0].get('returnCode') in ['00', '601', '602']:
                messages.success(
                    request,
                    f'Successfully decreased stock for {product.name} by {quantity}'
                )

                # Update local stock
                try:
                    stock = Stock.objects.get(product=product, store=store)
                    stock.quantity -= quantity
                    if stock.quantity < 0:
                        stock.quantity = 0
                    stock.save()
                except Stock.DoesNotExist:
                    pass

                # Create stock movement record
                StockMovement.objects.create(
                    product=product,
                    store=store,
                    movement_type='ADJUSTMENT',
                    quantity=-quantity,
                    reference=f'EFRIS-{result[0].get("referenceNo", "")}',
                    notes=remarks or f'Stock decrease via EFRIS - {adjust_type}'
                )

                return redirect('efris:stock_management_dashboard')
            else:
                error_msg = result[0].get('returnMessage', 'Unknown error') if result else 'No response'
                messages.error(request, f'Failed to decrease stock: {error_msg}')

        except Exception as e:
            messages.error(request, f'Error: {str(e)}')

    # Adjust types
    adjust_types = [
        ('101', 'Expired Goods'),
        ('102', 'Damaged Goods'),
        ('103', 'Personal Uses'),
        ('104', 'Others'),
        ('105', 'Raw Materials (Consumed)'),
    ]

    context = {
        'product': product,
        'stores': stores,
        'adjust_types': adjust_types,
    }

    return render(request, 'efris/stock_decrease.html', context)


@login_required
def stock_transfer(request):
    """Transfer stock between stores/branches (T139)"""
    company = request.tenant

    stores = Store.objects.filter(company=company)
    products = Product.objects.filter(
        efris_is_uploaded=True
    )

    if request.method == 'POST':
        try:
            source_store_id = request.POST.get('source_store_id')
            dest_store_id = request.POST.get('dest_store_id')
            product_id = request.POST.get('product_id')
            quantity = float(request.POST.get('quantity', 0))
            transfer_type = request.POST.get('transfer_type', '103')  # Default: Others
            remarks = request.POST.get('remarks', '')

            if source_store_id == dest_store_id:
                messages.error(request, 'Source and destination stores cannot be the same')
                return redirect('efris:stock_transfer')

            if quantity <= 0:
                messages.error(request, 'Quantity must be greater than 0')
                return redirect('efris:stock_transfer')

            source_store = get_object_or_404(Store, id=source_store_id, company=company)
            dest_store = get_object_or_404(Store, id=dest_store_id, company=company)
            product = get_object_or_404(Product, id=product_id)

            if not product.efris_goods_id:
                messages.error(request, f'Product {product.name} must be uploaded to EFRIS first')
                return redirect('efris:stock_transfer')

            if not source_store.efris_branch_id:
                messages.error(request, f'Source store {source_store.name} has no EFRIS branch ID')
                return redirect('efris:stock_transfer')

            if not dest_store.efris_branch_id:
                messages.error(request, f'Destination store {dest_store.name} has no EFRIS branch ID')
                return redirect('efris:stock_transfer')

            # Validate remarks for transfer_type=103
            if transfer_type == '103' and not remarks:
                messages.error(request, 'Remarks are required for transfer type "Others"')
                return redirect('efris:stock_transfer')

            # Prepare transfer item
            transfer_item = {
                "commodityGoodsId": product.category.efris_category_id,
                "goodsCode": product.sku,
                "measureUnit": product.unit_of_measure,
                "quantity": str(quantity),
                "remarks": remarks or f'Transfer from {source_store.name} to {dest_store.name}'
            }

            client = EnhancedEFRISAPIClient(company)
            auth_result = client.ensure_authenticated()
            if not auth_result.get("success"):
                messages.error(request, 'EFRIS authentication failed')
                return redirect('efris:stock_transfer')
            result = client.t139_transfer_stock(
                source_branch_id=source_store.efris_branch_id,
                destination_branch_id=dest_store.efris_branch_id,
                transfer_type_code=transfer_type,
                transfer_items=[transfer_item],
                remarks=remarks
            )

            if result and result[0].get('returnCode') in ['00', '601', '602']:
                messages.success(
                    request,
                    f'Successfully transferred {quantity} of {product.name} from {source_store.name} to {dest_store.name}'
                )

                # Update local stocks
                try:
                    source_stock = Stock.objects.get(product=product, store=source_store)
                    source_stock.quantity -= quantity
                    source_stock.save()
                except Stock.DoesNotExist:
                    pass

                dest_stock, created = Stock.objects.get_or_create(
                    product=product,
                    store=dest_store,
                    defaults={'quantity': 0}
                )
                dest_stock.quantity += quantity
                dest_stock.save()

                # Create stock movement records
                ref_no = f'TRANSFER-{result[0].get("referenceNo", "")}'

                StockMovement.objects.create(
                    product=product,
                    store=source_store,
                    movement_type='TRANSFER_OUT',
                    quantity=-quantity,
                    reference=ref_no,
                    notes=remarks or f'Transfer to {dest_store.name}'
                )

                StockMovement.objects.create(
                    product=product,
                    store=dest_store,
                    movement_type='TRANSFER_IN',
                    quantity=quantity,
                    reference=ref_no,
                    notes=remarks or f'Transfer from {source_store.name}'
                )

                return redirect('efris:stock_management_dashboard')
            else:
                error_msg = result[0].get('returnMessage', 'Unknown error') if result else 'No response'
                messages.error(request, f'Failed to transfer stock: {error_msg}')

        except Exception as e:
            messages.error(request, f'Error: {str(e)}')

    # Transfer types
    transfer_types = [
        ('101', 'Out of Stock'),
        ('102', 'Error'),
        ('103', 'Others'),
    ]

    context = {
        'stores': stores,
        'products': products,
        'transfer_types': transfer_types,
    }

    return render(request, 'efris/stock_transfer.html', context)


@login_required
def bulk_stock_sync(request):
    """Bulk sync stock records to EFRIS"""
    company = request.tenant

    if request.method == 'POST':
        store_id = request.POST.get('store_id')
        product_ids = request.POST.getlist('product_ids')

        try:
            store = None
            if store_id:
                store = get_object_or_404(Store, id=store_id, company=company)

            client = EnhancedEFRISAPIClient(company)
            auth_result = client.ensure_authenticated()
            if not auth_result.get("success"):
                messages.error(request, 'EFRIS authentication failed')
                return redirect('efris:stock_management_dashboard')

            results = client.bulk_sync_stock_to_efris(
                store=store,
                product_ids=product_ids if product_ids else None
            )

            messages.success(
                request,
                f"Bulk sync completed: {results['successful']}/{results['total']} successful"
            )

            if results['errors']:
                for error in results['errors'][:5]:
                    messages.warning(
                        request,
                        f"{error['product']} @ {error['store']}: {error['error']}"
                    )

        except Exception as e:
            messages.error(request, f'Bulk sync failed: {str(e)}')

        return redirect('efris:stock_management_dashboard')

    # Get products that need sync
    stocks_needing_sync = Stock.objects.filter(
        product__efris_is_uploaded=True,
        efris_sync_required=True
    ).select_related('product', 'store')

    stores = Store.objects.filter(company=company)

    context = {
        'stocks_needing_sync': stocks_needing_sync,
        'stores': stores,
    }

    return render(request, 'efris/bulk_stock_sync.html', context)


@login_required
def stock_records_query(request):
    """Query stock records from EFRIS (T145/T147)"""
    company = request.tenant

    records = None
    pagination_info = None

    if request.method == 'GET' and (request.GET.get('search') or request.GET.get('advanced_search')):
        page_no = request.GET.get('page', '1')
        page_size = request.GET.get('page_size', '10')

        try:
            client = EnhancedEFRISAPIClient(company)
            auth_result = client.ensure_authenticated()
            if not auth_result.get("success"):
                messages.error(request, 'EFRIS authentication failed')
                return redirect('efris:stock_management_dashboard')

            if request.GET.get('advanced_search'):
                # T147 - Advanced search
                result = client.t147_query_stock_records_advanced(
                    page_no=page_no,
                    page_size=page_size,
                    combine_keywords=request.GET.get('keywords', ''),
                    stock_in_type=request.GET.get('stock_in_type', ''),
                    start_date=request.GET.get('start_date', ''),
                    end_date=request.GET.get('end_date', ''),
                    supplier_tin=request.GET.get('supplier_tin', ''),
                    supplier_name=request.GET.get('supplier_name', '')
                )
            else:
                # T145 - Basic search
                result = client.t145_query_stock_records(
                    page_no=page_no,
                    page_size=page_size,
                    production_batch_no=request.GET.get('batch_no', ''),
                    invoice_no=request.GET.get('invoice_no', ''),
                    reference_no=request.GET.get('reference_no', '')
                )

            if result:
                records = result.get('records', [])
                pagination_info = result.get('page', {})
                messages.success(request, f'Found {len(records)} records')
            else:
                messages.warning(request, 'No records found')

        except Exception as e:
            messages.error(request, f'Query failed: {str(e)}')

    context = {
        'records': records,
        'pagination': pagination_info,
    }

    return render(request, 'efris/stock_records_query.html', context)


@login_required
def stock_record_detail(request, record_id):
    """View detailed information for a specific stock record (T148)"""
    company = request.tenant

    try:
        client = EnhancedEFRISAPIClient(company)
        record_detail = client.t148_query_stock_record_detail(record_id)

        if record_detail:
            messages.success(request, 'Record details retrieved successfully')
        else:
            messages.warning(request, 'No details found for this record')

    except Exception as e:
        messages.error(request, f'Failed to retrieve record details: {str(e)}')
        record_detail = None

    context = {
        'record_detail': record_detail,
        'record_id': record_id,
    }

    return render(request, 'efris/stock_record_detail.html', context)