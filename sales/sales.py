from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta, datetime
import json
import logging

from stores.models import Store
from .models import Sale, SaleItem, Payment, Receipt
from invoices.models import Invoice
from customers.models import Customer
from inventory.models import Product, Service
from stores.utils import get_user_accessible_stores, validate_store_access

logger = logging.getLogger(__name__)


def get_current_tenant(request):
    """Get current tenant from request. Defined here so all functions below can use it."""
    return getattr(request, 'tenant', None)



@login_required
def create_sale_enhanced(request):
    """Enhanced sale creation with preview, drafts, and workflow support"""

    if request.method == 'GET':
        return render_enhanced_sale_form(request)
    else:
        return process_enhanced_sale_creation(request)


def render_enhanced_sale_form(request):
    """Render enhanced sale creation form"""
    company = get_current_tenant(request)
    accessible_stores = get_user_accessible_stores(request.user).filter(
        is_active=True,
        company=company
    )

    # Get draft sales for sidebar
    draft_sales = Sale.objects.filter(
        store__in=accessible_stores,
        status='DRAFT',
        created_by=request.user
    ).select_related('customer', 'store').order_by('-created_at')[:10]

    # Get overdue invoices
    overdue_invoices = Sale.objects.filter(
        store__in=accessible_stores,
        document_type='INVOICE',
        payment_status='OVERDUE',
        is_voided=False
    ).select_related('customer', 'store').order_by('due_date')[:10]

    context = {
        'stores': accessible_stores,
        'draft_sales': draft_sales,
        'overdue_invoices': overdue_invoices,
        'document_types': Sale.DOCUMENT_TYPE_CHOICES,
        'payment_methods': Sale.PAYMENT_METHODS,
        'default_due_date': (timezone.now().date() + timedelta(days=30)).strftime('%Y-%m-%d'),
    }

    return render(request, 'sales/create_sale_enhanced.html', context)


def process_enhanced_sale_creation(request):
    """Process enhanced sale creation with workflow support"""

    action = request.POST.get('action')  # 'preview', 'save_draft', 'complete'

    try:
        sale_data = extract_sale_data(request)
        items_data = extract_items_data(request)

        if not items_data:
            messages.error(request, 'At least one item is required.')
            return render_enhanced_sale_form(request)

        # Validate based on document type and action
        if action == 'complete':
            validation_errors = validate_for_completion(sale_data, items_data)
            if validation_errors:
                for error in validation_errors:
                    messages.error(request, error)
                return render_enhanced_sale_form(request)

        # Create or update sale
        if action == 'preview':
            return show_preview(request, sale_data, items_data)
        elif action == 'save_draft':
            sale = save_as_draft(request, sale_data, items_data)
            messages.success(request, f'Draft saved: {sale.document_number}')
            return redirect('sales:edit_draft', pk=sale.pk)
        elif action == 'complete':
            sale = complete_sale(request, sale_data, items_data)
            messages.success(request, f'Sale completed: {sale.document_number}')
            return redirect('sales:sale_detail', pk=sale.pk)

    except Exception as e:
        logger.error(f"Error in enhanced sale creation: {e}", exc_info=True)
        messages.error(request, f'Error: {str(e)}')
        return render_enhanced_sale_form(request)


def extract_sale_data(request):
    """Extract and validate sale data from request"""
    store = get_object_or_404(
        Store,
        id=request.POST.get('store'),
        is_active=True
    )

    validate_store_access(request.user, store, action='create', raise_exception=True)

    customer_id = request.POST.get('customer')
    customer = None
    if customer_id:
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            raise ValueError(f"Customer id={customer_id} not found.")

    document_type = request.POST.get('document_type', 'RECEIPT')
    payment_method = request.POST.get('payment_method', 'CASH')

    # Invoice-specific fields
    due_date = None
    payment_terms = ''
    purchase_order = ''

    if document_type == 'INVOICE':
        due_date_str = request.POST.get('due_date')
        if due_date_str:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        else:
            due_date = timezone.now().date() + timedelta(days=30)

        payment_terms = request.POST.get('payment_terms', '')
        purchase_order = request.POST.get('purchase_order', '')

    return {
        'store': store,
        'customer': customer,
        'document_type': document_type,
        'payment_method': payment_method,
        'due_date': due_date,
        'payment_terms': payment_terms,
        'purchase_order': purchase_order,
        'notes': request.POST.get('notes', ''),
        'discount_amount': Decimal(request.POST.get('discount_amount', '0')),
        'currency': 'UGX',
    }


def extract_items_data(request):
    """Extract items data from request"""
    items_json = request.POST.get('items_data', '[]')

    # Debug logging
    logger.info(f"Items JSON received: {items_json}")

    try:
        items_data = json.loads(items_json) if items_json else []
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return []

    if not items_data:
        logger.warning("No items data found in request")
        return []

    # B3 fix: batch-fetch all products and services in 2 queries instead of N
    product_ids = [i['product_id'] for i in items_data if i.get('item_type', 'PRODUCT') == 'PRODUCT' and i.get('product_id')]
    service_ids = [i['service_id'] for i in items_data if i.get('item_type') == 'SERVICE' and i.get('service_id')]
    products_map = {p.id: p for p in Product.objects.filter(id__in=product_ids, is_active=True)}
    services_map = {s.id: s for s in Service.objects.filter(id__in=service_ids, is_active=True)}

    validated_items = []

    for item in items_data:
        item_type = item.get('item_type', 'PRODUCT')

        try:
            if item_type == 'PRODUCT':
                product_id = item.get('product_id')
                if not product_id:
                    logger.warning(f"Missing product_id in item: {item}")
                    continue

                product = products_map.get(int(product_id))
                if not product:
                    logger.error(f"Product id={product_id} not found or inactive")
                    continue

                validated_items.append({
                    'item_type': 'PRODUCT',
                    'product': product,
                    'service': None,
                    'quantity': Decimal(str(item.get('quantity', 1))),
                    'unit_price': Decimal(str(item.get('unit_price', 0))),
                    'tax_rate': item.get('tax_rate', 'A'),
                    'discount': Decimal(str(item.get('discount', '0'))),
                    'description': item.get('description', ''),
                })
            elif item_type == 'SERVICE':
                service_id = item.get('service_id')
                if not service_id:
                    logger.warning(f"Missing service_id in item: {item}")
                    continue

                service = services_map.get(int(service_id))
                if not service:
                    logger.error(f"Service id={service_id} not found or inactive")
                    continue

                validated_items.append({
                    'item_type': 'SERVICE',
                    'product': None,
                    'service': service,
                    'quantity': Decimal(str(item.get('quantity', 1))),
                    'unit_price': Decimal(str(item.get('unit_price', 0))),
                    'tax_rate': item.get('tax_rate', 'A'),
                    'discount': Decimal(str(item.get('discount', '0'))),
                    'description': item.get('description', ''),
                })
        except Exception as e:
            logger.error(f"Error processing item: {e}", exc_info=True)
            continue

    logger.info(f"Validated {len(validated_items)} items")
    return validated_items

def validate_for_completion(sale_data, items_data):
    """Validate sale data before completion"""
    errors = []

    # Validate invoice-specific requirements
    if sale_data['document_type'] == 'INVOICE':
        if not sale_data['due_date']:
            errors.append("Due date is required for invoices")

        if not sale_data['customer']:
            errors.append("Customer is required for invoices")

    # Validate stock for products in receipts/invoices
    if sale_data['document_type'] in ['RECEIPT', 'INVOICE']:
        stock_errors = validate_stock_availability(
            sale_data['store'],
            items_data
        )
        errors.extend(stock_errors)

    return errors


def show_preview(request, sale_data, items_data):
    """Show preview of sale before completion"""
    # Calculate totals
    subtotal = sum(
        item['quantity'] * item['unit_price']
        for item in items_data
    )

    discount = sale_data['discount_amount']

    # Calculate tax
    tax_amount = Decimal('0')
    for item in items_data:
        item_total = item['quantity'] * item['unit_price']
        item_discount = (item['discount'] / Decimal('100')) * item_total
        item_net = item_total - item_discount

        if item['tax_rate'] in ['A', 'D']:
            tax_amount += (item_net / Decimal('1.18') * Decimal('0.18'))

    # B6 fix: tax is inclusive (embedded in unit_price), so total = subtotal - discount.
    # Tax amount is informational only — do not add it again.
    # The real Sale.total_amount = subtotal - discount (tax already in price).
    total = subtotal - discount

    context = {
        'sale_data': sale_data,
        'items_data': items_data,
        'subtotal': subtotal,
        'discount': discount,
        'tax_amount': tax_amount,   # shown as informational, not added to total
        'total': total,
        'is_preview': True,
    }

    return render(request, 'sales/preview_sale.html', context)


@transaction.atomic
def save_as_draft(request, sale_data, items_data):
    """Save sale as draft"""
    sale = Sale.objects.create(
        store=sale_data['store'],
        created_by=request.user,
        customer=sale_data['customer'],
        document_type=sale_data['document_type'],
        payment_method=sale_data['payment_method'],
        due_date=sale_data.get('due_date'),
        notes=sale_data['notes'],
        discount_amount=sale_data['discount_amount'],
        currency=sale_data['currency'],
        status='DRAFT',
        payment_status='NOT_APPLICABLE' if sale_data['document_type'] in ['PROFORMA', 'ESTIMATE'] else 'PENDING',
    )

    # B5 fix: suppress per-item update_totals signal, call once at end
    for item_data in items_data:
        item = SaleItem(
            sale=sale,
            item_type=item_data['item_type'],
            product=item_data.get('product'),
            service=item_data.get('service'),
            quantity=item_data['quantity'],
            unit_price=item_data['unit_price'],
            tax_rate=item_data['tax_rate'],
            discount=item_data['discount'],
            description=item_data.get('description', ''),
        )
        item._skip_sale_update = True
        item.save()

    sale.update_totals()

    # Create invoice detail if invoice type
    if sale_data['document_type'] == 'INVOICE':
        Invoice.objects.create(
            sale=sale,
            store=sale_data['store'],
            terms=sale_data.get('payment_terms', ''),
            purchase_order=sale_data.get('purchase_order', ''),
            created_by=request.user,
        )

    return sale


@transaction.atomic
def complete_sale(request, sale_data, items_data):
    """Complete sale (non-draft)"""
    # B10 fix: PROFORMA and ESTIMATE are not payable documents
    doc_type = sale_data['document_type']
    if doc_type == 'RECEIPT':
        status, payment_status = 'COMPLETED', 'PAID'
    elif doc_type == 'INVOICE':
        status, payment_status = 'PENDING_PAYMENT', 'PENDING'
    else:  # PROFORMA, ESTIMATE
        status, payment_status = 'DRAFT', 'NOT_APPLICABLE'

    sale = Sale.objects.create(
        store=sale_data['store'],
        created_by=request.user,
        customer=sale_data['customer'],
        document_type=sale_data['document_type'],
        payment_method=sale_data['payment_method'],
        due_date=sale_data.get('due_date'),
        notes=sale_data['notes'],
        discount_amount=sale_data['discount_amount'],
        currency=sale_data['currency'],
        status=status,
        payment_status=payment_status,
    )

    # B5 fix: suppress per-item update_totals signal, call once at end
    for item_data in items_data:
        item = SaleItem(
            sale=sale,
            item_type=item_data['item_type'],
            product=item_data.get('product'),
            service=item_data.get('service'),
            quantity=item_data['quantity'],
            unit_price=item_data['unit_price'],
            tax_rate=item_data['tax_rate'],
            discount=item_data['discount'],
            description=item_data.get('description', ''),
        )
        item._skip_sale_update = True
        item.save()

    sale.update_totals()

    # Create document-specific records
    if sale_data['document_type'] == 'RECEIPT':
        Receipt.objects.create(
            sale=sale,
            printed_by=request.user,
        )

        # Create payment record
        Payment.objects.create(
            sale=sale,
            store=sale.store,
            amount=sale.total_amount,
            payment_method=sale.payment_method,
            is_confirmed=True,
            confirmed_at=timezone.now(),
            created_by=request.user,
            payment_type='FULL',
        )
    elif sale_data['document_type'] == 'INVOICE':
        Invoice.objects.create(
            sale=sale,
            store=sale_data['store'],
            terms=sale_data.get('payment_terms', ''),
            purchase_order=sale_data.get('purchase_order', ''),
            created_by=request.user,
        )

    return sale


@login_required
def edit_draft(request, pk):
    """Edit draft sale"""
    sale = get_object_or_404(
        Sale.objects.select_related('store', 'customer'),
        pk=pk,
        status='DRAFT'
    )

    validate_store_access(request.user, sale.store, action='change', raise_exception=True)

    if request.method == 'POST':
        return update_draft(request, sale)

    # GET - show edit form
    items = sale.items.select_related('product', 'service').all()

    context = {
        'sale': sale,
        'items': items,
        'is_editing': True,
        'stores': get_user_accessible_stores(request.user).filter(is_active=True),
        'document_types': Sale.DOCUMENT_TYPE_CHOICES,
        'payment_methods': Sale.PAYMENT_METHODS,
    }

    return render(request, 'sales/edit_draft.html', context)


@transaction.atomic
def update_draft(request, sale):
    """Update draft sale"""
    try:
        # Update sale fields
        sale_data = extract_sale_data(request)

        sale.customer = sale_data['customer']
        sale.document_type = sale_data['document_type']
        sale.payment_method = sale_data['payment_method']
        sale.due_date = sale_data.get('due_date')
        sale.notes = sale_data['notes']
        sale.discount_amount = sale_data['discount_amount']

        # Delete existing items
        sale.items.all().delete()

        # Add new items — B5 fix: suppress per-item totals, call once at end
        items_data = extract_items_data(request)
        for item_data in items_data:
            item = SaleItem(
                sale=sale,
                item_type=item_data['item_type'],
                product=item_data.get('product'),
                service=item_data.get('service'),
                quantity=item_data['quantity'],
                unit_price=item_data['unit_price'],
                tax_rate=item_data['tax_rate'],
                discount=item_data['discount'],
                description=item_data.get('description', ''),
            )
            item._skip_sale_update = True
            item.save()

        # B7 fix: update_totals() calls save(update_fields=...) internally —
        # do NOT call sale.save() again after it (would overwrite those fields).
        sale.update_totals()

        # Update invoice if exists
        if sale.document_type == 'INVOICE' and hasattr(sale, 'invoice_detail'):
            invoice = sale.invoice_detail
            invoice.terms = sale_data.get('payment_terms', '')
            invoice.purchase_order = sale_data.get('purchase_order', '')
            invoice.save()

        messages.success(request, f'Draft {sale.document_number} updated successfully')
        return redirect('sales:edit_draft', pk=sale.pk)

    except Exception as e:
        logger.error(f"Error updating draft: {e}", exc_info=True)
        messages.error(request, f'Error updating draft: {str(e)}')
        return redirect('sales:edit_draft', pk=sale.pk)


@login_required
def record_payment(request, pk):
    """Record payment for invoice"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

    try:
        amount = Decimal(request.POST.get('amount', '0'))
        payment_method = request.POST.get('payment_method', 'CASH')
        transaction_ref = request.POST.get('transaction_reference', '')
        notes = request.POST.get('notes', '')

        if amount <= 0:
            return JsonResponse({'success': False, 'error': 'Amount must be positive'}, status=400)

        # B8 fix: lock the sale row inside a transaction to prevent concurrent
        # payments from both passing the outstanding-balance check simultaneously.
        with transaction.atomic():
            sale = get_object_or_404(
                Sale.objects.select_for_update(), pk=pk, document_type='INVOICE'
            )
            validate_store_access(request.user, sale.store, action='change', raise_exception=True)

            outstanding = sale.amount_outstanding
            if amount > outstanding:
                return JsonResponse({
                    'success': False,
                    'error': f'Amount exceeds outstanding balance of {outstanding}'
                }, status=400)

            # Create payment
            payment = Payment.objects.create(
            sale=sale,
            store=sale.store,
            amount=amount,
            payment_method=payment_method,
            transaction_reference=transaction_ref,
            is_confirmed=True,
            confirmed_at=timezone.now(),
            created_by=request.user,
            notes=notes,
            payment_type='FULL' if amount >= outstanding else 'PARTIAL',
        )

        # Update sale payment status
        total_paid = sale.amount_paid
        if total_paid >= sale.total_amount:
            sale.payment_status = 'PAID'
            sale.status = 'COMPLETED'
        else:
            sale.payment_status = 'PARTIALLY_PAID'

        sale.save(update_fields=['payment_status', 'status'])

        return JsonResponse({
            'success': True,
            'message': 'Payment recorded successfully',
            'payment_id': payment.id,
            'total_paid': str(total_paid),
            'outstanding': str(sale.amount_outstanding),
            'payment_status': sale.get_payment_status_display(),
        })

    except Exception as e:
        logger.error(f"Error recording payment: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def validate_stock_availability(store, items_data):
    """Validate stock for products — B9 fix: single IN query instead of N queries."""
    from inventory.models import Stock

    errors = []

    product_items = [i for i in items_data if i['item_type'] == 'PRODUCT' and i.get('product')]
    if not product_items:
        return errors

    product_ids = [i['product'].id for i in product_items]
    stock_map = {
        s.product_id: s
        for s in Stock.objects.filter(product_id__in=product_ids, store=store)
    }

    for item in product_items:
        product = item['product']
        stock = stock_map.get(product.id)

        if not stock:
            errors.append(f'No stock record for {product.name}')
            continue

        if stock.quantity < item['quantity']:
            errors.append(
                f'Insufficient stock for {product.name}. '
                f'Available: {stock.quantity}, Required: {item["quantity"]}'
            )

    return errors