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


@transaction.atomic
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
    customer = Customer.objects.get(id=customer_id) if customer_id else None

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

    validated_items = []

    for item in items_data:
        item_type = item.get('item_type', 'PRODUCT')

        try:
            if item_type == 'PRODUCT':
                product_id = item.get('product_id')
                if not product_id:
                    logger.warning(f"Missing product_id in item: {item}")
                    continue

                product = Product.objects.get(id=product_id, is_active=True)
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

                service = Service.objects.get(id=service_id, is_active=True)
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
        except (Product.DoesNotExist, Service.DoesNotExist) as e:
            logger.error(f"Item not found: {e}")
            continue
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

    total = subtotal - discount

    context = {
        'sale_data': sale_data,
        'items_data': items_data,
        'subtotal': subtotal,
        'discount': discount,
        'tax_amount': tax_amount,
        'total': total,
        'is_preview': True,
    }

    return render(request, 'sales/preview_sale.html', context)


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

    # Add items
    for item_data in items_data:
        SaleItem.objects.create(
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


def complete_sale(request, sale_data, items_data):
    """Complete sale (non-draft)"""
    status = 'COMPLETED' if sale_data['document_type'] == 'RECEIPT' else 'PENDING_PAYMENT'
    payment_status = 'PAID' if sale_data['document_type'] == 'RECEIPT' else 'PENDING'

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

    # Add items
    for item_data in items_data:
        SaleItem.objects.create(
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

        # Add new items
        items_data = extract_items_data(request)
        for item_data in items_data:
            SaleItem.objects.create(
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

        sale.update_totals()
        sale.save()

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

    sale = get_object_or_404(Sale, pk=pk, document_type='INVOICE')

    validate_store_access(request.user, sale.store, action='change', raise_exception=True)

    try:
        amount = Decimal(request.POST.get('amount', '0'))
        payment_method = request.POST.get('payment_method', 'CASH')
        transaction_ref = request.POST.get('transaction_reference', '')
        notes = request.POST.get('notes', '')

        if amount <= 0:
            return JsonResponse({'success': False, 'error': 'Amount must be positive'}, status=400)

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
    """Validate stock for products"""
    from inventory.models import Stock

    errors = []

    for item in items_data:
        if item['item_type'] != 'PRODUCT':
            continue

        product = item['product']
        stock = Stock.objects.filter(product=product, store=store).first()

        if not stock:
            errors.append(f'No stock record for {product.name}')
            continue

        if stock.quantity < item['quantity']:
            errors.append(
                f'Insufficient stock for {product.name}. '
                f'Available: {stock.quantity}, Required: {item["quantity"]}'
            )

    return errors


def get_current_tenant(request):
    """Get current tenant from request"""
    return getattr(request, 'tenant', None)

