from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.db.models import Q, Sum
from django.db import transaction
from django.utils import timezone
from django.template.loader import render_to_string
from django_tenants.utils import tenant_context
from django.core.exceptions import PermissionDenied, ValidationError  # ADDED
from decimal import Decimal
import json
import logging
from datetime import timedelta
from weasyprint import HTML, CSS
from io import BytesIO

# ADD THESE IMPORTS
from stores.utils import validate_store_access, get_user_accessible_stores

from .models import Sale, SaleItem, Payment
from inventory.models import Product, Stock, Service
from customers.models import Customer
from stores.models import Store

logger = logging.getLogger(__name__)


# ==================== HELPER FUNCTIONS ====================
def get_current_tenant(request):
    """Get current tenant from request"""
    return getattr(request, 'tenant', None)


def get_user_stores(user, company):
    """Get stores accessible by user"""
    # Use the utility function
    return get_user_accessible_stores(user).filter(
        company=company,
        is_active=True
    )


# ==================== RECEIPT CREATION ====================
@login_required
@permission_required("sales.add_sale", raise_exception=True)
@require_http_methods(["GET", "POST"])
def create_receipt(request):
    """Create receipt (immediate payment) - Step 1: Build Receipt"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('sales:sales_list')

    with tenant_context(company):
        if request.method == 'GET':
            return render_receipt_form(request, company)
        else:
            return process_receipt_draft(request, company)


def render_receipt_form(request, company):
    """Render receipt creation form"""
    user = request.user
    stores = get_user_stores(user, company)

    if not stores.exists():
        return render(request, 'sales/create_receipt.html', {
            'stores': stores,
            'no_stores': True,
            'error_message': 'No stores available.'
        })

    context = {
        'stores': stores,
        'company': company,
        'page_title': 'Create Receipt',
        'document_type': 'RECEIPT',
        'default_store': stores.first(),
        'payment_methods': Sale.PAYMENT_METHODS,
    }

    return render(request, 'sales/create_receipt.html', context)


@transaction.atomic
def process_receipt_draft(request, company):
    """Process receipt and create draft"""
    try:
        # Extract data
        sale_data = extract_receipt_data(request.POST, request.user, company)
        items_data = json.loads(request.POST.get('items_data', '[]'))

        if not items_data:
            messages.error(request, 'At least one item is required.')
            return render_receipt_form(request, company)

        # Validate stock
        stock_errors = validate_stock_for_items(sale_data['store'], items_data)
        if stock_errors:
            for error in stock_errors:
                messages.error(request, error)
            return render_receipt_form(request, company)

        # Create draft receipt
        receipt = Sale.objects.create(
            store=sale_data['store'],
            created_by=request.user,
            customer=sale_data.get('customer'),
            document_type='RECEIPT',
            payment_method=sale_data['payment_method'],
            currency=sale_data.get('currency', 'UGX'),
            discount_amount=sale_data.get('discount_amount', 0),
            notes=sale_data.get('notes', ''),
            status='DRAFT',
        )

        # Add items
        for item_data in items_data:
            create_sale_item_from_data(receipt, item_data)

        receipt.update_totals()

        messages.success(
            request,
            f'Receipt draft #{receipt.document_number} created. Review and complete.'
        )

        return redirect('sales:receipt_preview', pk=receipt.pk)

    except Exception as e:
        logger.error(f"Error creating receipt draft: {e}", exc_info=True)
        messages.error(request, f'Error: {str(e)}')
        return render_receipt_form(request, company)


@login_required
@permission_required("sales.view_sale", raise_exception=True)
def receipt_preview(request, pk):
    """Preview receipt before completion - Step 2: Preview & Print"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('sales:sales_list')

    with tenant_context(company):
        receipt = get_object_or_404(
            Sale.objects.filter(
                document_type='RECEIPT',
                store__company=company
            ).select_related('customer', 'store', 'created_by')
            .prefetch_related('items__product', 'items__service'),
            pk=pk
        )

        # Validate store access
        try:
            validate_store_access(request.user, receipt.store, action='view', raise_exception=True)
        except PermissionDenied as e:
            messages.error(request, str(e))
            return redirect('sales:sales_list')

        context = {
            'receipt': receipt,
            'company': company,
            'can_edit': receipt.status == 'DRAFT',
            'can_complete': receipt.status == 'DRAFT',
        }

        return render(request, 'sales/receipt_preview.html', context)


@login_required
@permission_required("sales.change_sale", raise_exception=True)
def receipt_print_pdf(request, pk):
    """Generate printable receipt PDF"""
    company = get_current_tenant(request)
    if not company:
        return HttpResponse('No company context', status=403)

    with tenant_context(company):
        receipt = get_object_or_404(
            Sale.objects.filter(
                document_type='RECEIPT',
                store__company=company
            ).select_related('customer', 'store')
            .prefetch_related('items__product', 'items__service'),
            pk=pk
        )

        # Validate store access
        try:
            validate_store_access(request.user, receipt.store, action='view', raise_exception=True)
        except PermissionDenied as e:
            return HttpResponse('Access denied to this store', status=403)

        # Render HTML
        html_string = render_to_string('sales/receipt_print_template.html', {
            'receipt': receipt,
            'company': company,
            'store': receipt.store,
        })

        # Generate PDF
        html = HTML(string=html_string)
        pdf_file = html.write_pdf()

        # Return PDF response
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="receipt_{receipt.document_number}.pdf"'

        return response


@login_required
@permission_required("sales.change_sale", raise_exception=True)
@require_POST
def complete_receipt(request, pk):
    """Complete receipt - Step 3: Finalize & Save"""
    company = get_current_tenant(request)
    if not company:
        return JsonResponse({'success': False, 'error': 'No company context'})

    with tenant_context(company):
        try:
            receipt = get_object_or_404(
                Sale.objects.filter(
                    document_type='RECEIPT',
                    status='DRAFT',
                    store__company=company
                ),
                pk=pk
            )

            # Validate store access
            try:
                validate_store_access(request.user, receipt.store, action='change', raise_exception=True)
            except PermissionDenied as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                })

            with transaction.atomic():
                # Validate stock again before completion
                stock_errors = validate_receipt_stock(receipt)
                if stock_errors:
                    return JsonResponse({
                        'success': False,
                        'errors': stock_errors
                    })

                # Deduct stock for all items
                for item in receipt.items.all():
                    if item.item_type == 'PRODUCT' and item.product:
                        deduct_stock_for_item(item)

                # Mark as completed
                receipt.status = 'COMPLETED'
                receipt.payment_status = 'PAID'  # Receipts are always paid
                receipt.save()

                # Create payment record
                Payment.objects.create(
                    sale=receipt,
                    store=receipt.store,
                    amount=receipt.total_amount,
                    payment_method=receipt.payment_method,
                    is_confirmed=True,
                    confirmed_at=timezone.now(),
                    created_by=request.user,
                    payment_type='FULL'
                )

                # Auto-fiscalize based on store's EFRIS config
                try:
                    store_config = receipt.store.effective_efris_config
                    if store_config.get('enabled', False) and store_config.get('auto_fiscalize_sales', False):
                        # Queue for fiscalization
                        from .tasks import fiscalize_invoice_async
                        fiscalize_invoice_async.delay(
                            receipt.id,
                            user_id=request.user.pk
                        )
                        logger.info(f"Queued receipt {receipt.document_number} for auto-fiscalization")
                except Exception as e:
                    logger.error(f"Auto-fiscalization check failed for receipt {receipt.id}: {e}")

                messages.success(
                    request,
                    f'Receipt #{receipt.document_number} completed successfully!'
                )

                return JsonResponse({
                    'success': True,
                    'message': 'Receipt completed',
                    'receipt_number': receipt.document_number,
                    'redirect_url': f'/sales/receipt/{receipt.pk}/print/'
                })

        except Exception as e:
            logger.error(f"Error completing receipt: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            })


# ==================== INVOICE CREATION ====================
@login_required
@permission_required("sales.add_sale", raise_exception=True)
@require_http_methods(["GET", "POST"])
def create_invoice(request):
    """Create invoice (credit sale) - Step 1: Build Invoice"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('sales:sales_list')

    with tenant_context(company):
        if request.method == 'GET':
            return render_invoice_form(request, company)
        else:
            return process_invoice_draft(request, company)


def render_invoice_form(request, company):
    """Render invoice creation form"""
    user = request.user
    stores = get_user_stores(user, company)

    if not stores.exists():
        return render(request, 'sales/create_invoice.html', {
            'stores': stores,
            'no_stores': True,
            'error_message': 'No stores available.'
        })

    context = {
        'stores': stores,
        'company': company,
        'page_title': 'Create Invoice',
        'document_type': 'INVOICE',
        'default_store': stores.first(),
        'payment_methods': Sale.PAYMENT_METHODS,
    }

    return render(request, 'sales/create_invoice.html', context)


@transaction.atomic
def process_invoice_draft(request, company):
    """Process invoice and create draft"""
    try:
        # Extract data
        sale_data = extract_invoice_data(request.POST, request.user, company)
        items_data = json.loads(request.POST.get('items_data', '[]'))

        if not items_data:
            messages.error(request, 'At least one item is required.')
            return render_invoice_form(request, company)

        # For invoices, stock validation is optional (depends on policy)
        # We'll validate but allow proceeding with warnings

        # Create draft invoice
        invoice = Sale.objects.create(
            store=sale_data['store'],
            created_by=request.user,
            customer=sale_data.get('customer'),
            document_type='INVOICE',
            payment_method=sale_data['payment_method'],
            currency=sale_data.get('currency', 'UGX'),
            discount_amount=sale_data.get('discount_amount', 0),
            notes=sale_data.get('notes', ''),
            due_date=sale_data.get('due_date'),
            status='DRAFT',
        )

        # Add items
        for item_data in items_data:
            create_sale_item_from_data(invoice, item_data)

        invoice.update_totals()

        messages.success(
            request,
            f'Invoice draft #{invoice.document_number} created. Review and complete.'
        )

        return redirect('sales:invoice_preview', pk=invoice.pk)

    except Exception as e:
        logger.error(f"Error creating invoice draft: {e}", exc_info=True)
        messages.error(request, f'Error: {str(e)}')
        return render_invoice_form(request, company)


@login_required
@permission_required("sales.view_sale", raise_exception=True)
def invoice_preview(request, pk):
    """Preview invoice before completion - Step 2: Preview & Print"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('sales:sales_list')

    with tenant_context(company):
        invoice = get_object_or_404(
            Sale.objects.filter(
                document_type='INVOICE',
                store__company=company
            ).select_related('customer', 'store', 'created_by')
            .prefetch_related('items__product', 'items__service'),
            pk=pk
        )

        # Validate store access
        try:
            validate_store_access(request.user, invoice.store, action='view', raise_exception=True)
        except PermissionDenied as e:
            messages.error(request, str(e))
            return redirect('sales:sales_list')

        context = {
            'invoice': invoice,
            'company': company,
            'can_edit': invoice.status == 'DRAFT',
            'can_complete': invoice.status == 'DRAFT',
        }

        return render(request, 'sales/invoice_preview.html', context)


@login_required
@permission_required("sales.change_sale", raise_exception=True)
def invoice_print_pdf(request, pk):
    """Generate printable invoice PDF"""
    company = get_current_tenant(request)
    if not company:
        return HttpResponse('No company context', status=403)

    with tenant_context(company):
        invoice = get_object_or_404(
            Sale.objects.filter(
                document_type='INVOICE',
                store__company=company
            ).select_related('customer', 'store')
            .prefetch_related('items__product', 'items__service'),
            pk=pk
        )

        # Validate store access
        try:
            validate_store_access(request.user, invoice.store, action='view', raise_exception=True)
        except PermissionDenied as e:
            return HttpResponse('Access denied to this store', status=403)

        # Render HTML
        html_string = render_to_string('sales/invoice_print_template.html', {
            'invoice': invoice,
            'company': company,
            'store': invoice.store,
        })

        # Generate PDF
        html = HTML(string=html_string)
        pdf_file = html.write_pdf()

        # Return PDF response
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="invoice_{invoice.document_number}.pdf"'

        return response


@login_required
@permission_required("sales.change_sale", raise_exception=True)
@require_POST
def complete_invoice(request, pk):
    """Complete invoice - Step 3: Finalize & Save"""
    company = get_current_tenant(request)
    if not company:
        return JsonResponse({'success': False, 'error': 'No company context'})

    with tenant_context(company):
        try:
            invoice = get_object_or_404(
                Sale.objects.filter(
                    document_type='INVOICE',
                    status='DRAFT',
                    store__company=company
                ),
                pk=pk
            )

            # Validate store access
            try:
                validate_store_access(request.user, invoice.store, action='change', raise_exception=True)
            except PermissionDenied as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                })

            with transaction.atomic():
                # Deduct stock for product items
                for item in invoice.items.all():
                    if item.item_type == 'PRODUCT' and item.product:
                        deduct_stock_for_item(item)

                # Set appropriate status based on payment method
                if invoice.payment_method == 'CREDIT':
                    invoice.status = 'PENDING_PAYMENT'
                    invoice.payment_status = 'PENDING'
                else:
                    # Cash/immediate payment
                    invoice.status = 'COMPLETED'
                    invoice.payment_status = 'PAID'

                    # Create payment record
                    Payment.objects.create(
                        sale=invoice,
                        store=invoice.store,
                        amount=invoice.total_amount,
                        payment_method=invoice.payment_method,
                        is_confirmed=True,
                        confirmed_at=timezone.now(),
                        created_by=request.user,
                        payment_type='FULL'
                    )

                invoice.save()

                # Create invoice detail
                from invoices.models import Invoice as InvoiceDetail
                InvoiceDetail.objects.create(
                    sale=invoice,
                    store=invoice.store,
                    terms=request.POST.get('terms', ''),
                    purchase_order=request.POST.get('purchase_order', ''),
                    created_by=request.user
                )

                # Auto-fiscalize based on store's EFRIS config
                try:
                    store_config = invoice.store.effective_efris_config
                    if store_config.get('enabled', False) and store_config.get('auto_fiscalize_sales', False):
                        # Queue for fiscalization
                        from .tasks import fiscalize_invoice_async
                        fiscalize_invoice_async.delay(
                            invoice.id,
                            user_id=request.user.pk
                        )
                        logger.info(f"Queued invoice {invoice.document_number} for auto-fiscalization")
                except Exception as e:
                    logger.error(f"Auto-fiscalization check failed for invoice {invoice.id}: {e}")

                messages.success(
                    request,
                    f'Invoice #{invoice.document_number} completed successfully!'
                )

                return JsonResponse({
                    'success': True,
                    'message': 'Invoice completed',
                    'invoice_number': invoice.document_number,
                    'redirect_url': f'/sales/invoice/{invoice.pk}/detail/'
                })

        except Exception as e:
            logger.error(f"Error completing invoice: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            })


# ==================== DRAFT MANAGEMENT ====================
@login_required
@permission_required("sales.view_sale", raise_exception=True)
def drafts_list(request):
    """List all draft receipts and invoices"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('sales:sales_list')

    with tenant_context(company):
        document_type = request.GET.get('type', 'all')

        drafts = Sale.objects.filter(
            store__company=company,
            status='DRAFT',
            created_by=request.user
        ).select_related('customer', 'store')

        if document_type != 'all':
            drafts = drafts.filter(document_type=document_type.upper())

        drafts = drafts.order_by('-created_at')

        context = {
            'drafts': drafts,
            'document_type': document_type,
            'company': company,
        }

        return render(request, 'sales/drafts_list.html', context)


@login_required
@permission_required("sales.change_sale", raise_exception=True)
def edit_draft(request, pk):
    """Edit draft receipt or invoice"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('sales:drafts_list')

    with tenant_context(company):
        draft = get_object_or_404(
            Sale.objects.filter(
                status='DRAFT',
                store__company=company
            ),
            pk=pk
        )

        # Validate store access
        try:
            validate_store_access(request.user, draft.store, action='change', raise_exception=True)
        except PermissionDenied as e:
            messages.error(request, str(e))
            return redirect('sales:drafts_list')

        # Redirect to appropriate edit page
        if draft.document_type == 'RECEIPT':
            return render_receipt_edit(request, draft, company)
        elif draft.document_type == 'INVOICE':
            return render_invoice_edit(request, draft, company)
        else:
            messages.error(request, 'Invalid document type')
            return redirect('sales:drafts_list')


def render_receipt_edit(request, receipt, company):
    """Render receipt edit form with existing data"""
    stores = get_user_stores(request.user, company)

    # Prepare items data
    items_data = []
    for item in receipt.items.all():
        items_data.append({
            'item_type': item.item_type,
            'product_id': item.product.id if item.product else None,
            'service_id': item.service.id if item.service else None,
            'name': item.item_name,
            'quantity': float(item.quantity),
            'unit_price': float(item.unit_price),
            'tax_rate': item.tax_rate,
            'discount': float(item.discount),
        })

    context = {
        'stores': stores,
        'company': company,
        'receipt': receipt,
        'existing_items': json.dumps(items_data),
        'is_edit': True,
        'document_type': 'RECEIPT',
    }

    return render(request, 'sales/create_receipt.html', context)


def render_invoice_edit(request, invoice, company):
    """Render invoice edit form with existing data"""
    stores = get_user_stores(request.user, company)

    # Prepare items data
    items_data = []
    for item in invoice.items.all():
        items_data.append({
            'item_type': item.item_type,
            'product_id': item.product.id if item.product else None,
            'service_id': item.service.id if item.service else None,
            'name': item.item_name,
            'quantity': float(item.quantity),
            'unit_price': float(item.unit_price),
            'tax_rate': item.tax_rate,
            'discount': float(item.discount),
        })

    context = {
        'stores': stores,
        'company': company,
        'invoice': invoice,
        'existing_items': json.dumps(items_data),
        'is_edit': True,
        'document_type': 'INVOICE',
    }

    return render(request, 'sales/create_invoice.html', context)


@login_required
@permission_required("sales.delete_sale", raise_exception=True)
@require_POST
def delete_draft(request, pk):
    """Delete draft"""
    company = get_current_tenant(request)
    if not company:
        return JsonResponse({'success': False, 'error': 'No company context'})

    with tenant_context(company):
        try:
            draft = get_object_or_404(
                Sale.objects.filter(
                    status='DRAFT',
                    store__company=company
                ),
                pk=pk
            )

            # Validate store access
            try:
                validate_store_access(request.user, draft.store, action='delete', raise_exception=True)
            except PermissionDenied as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                })

            document_number = draft.document_number
            draft.delete()

            return JsonResponse({
                'success': True,
                'message': f'Draft {document_number} deleted successfully'
            })

        except Exception as e:
            logger.error(f"Error deleting draft: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            })


# ==================== HELPER FUNCTIONS ====================
def extract_receipt_data(post_data, user, company):
    """Extract and validate receipt data"""
    store_id = post_data.get('store')
    store = Store.objects.get(id=store_id, company=company)

    # Validate store access
    try:
        validate_store_access(user, store, action='view', raise_exception=True)
    except PermissionDenied as e:
        raise ValidationError(str(e))

    # Check if store allows sales
    if not store.allows_sales:
        raise ValidationError(f"Store '{store.name}' does not allow sales.")

    customer_id = post_data.get('customer')
    customer = None
    if customer_id:
        customer = Customer.objects.get(id=customer_id,store=store)

    return {
        'store': store,
        'customer': customer,
        'payment_method': post_data.get('payment_method', 'CASH'),
        'currency': post_data.get('currency', 'UGX'),
        'discount_amount': Decimal(post_data.get('discount_amount', '0')),
        'notes': post_data.get('notes', ''),
    }


def extract_invoice_data(post_data, user, company):
    """Extract and validate invoice data"""
    # Get payment method FIRST, before any exceptions
    payment_method = post_data.get('payment_method', 'CASH')

    store_id = post_data.get('store')

    # Validate store_id exists
    if not store_id:
        raise ValidationError('Store is required.')

    try:
        store = Store.objects.get(id=store_id, company=company)
    except Store.DoesNotExist:
        raise ValidationError('Store not found.')

    # Validate store access
    try:
        validate_store_access(user, store, action='view', raise_exception=True)
    except PermissionDenied as e:
        raise ValidationError(str(e))

    # Check if store allows sales
    if not store.allows_sales:
        raise ValidationError(f"Store '{store.name}' does not allow sales.")

    customer_id = post_data.get('customer')
    customer = None
    if customer_id:
        try:
            customer = Customer.objects.get(id=customer_id, store=store)
        except Customer.DoesNotExist:
            raise ValidationError('Customer not found.')

    # Get due date - REQUIRED for ALL invoices, not just credit sales
    due_date = None
    due_date_str = post_data.get('due_date')

    if due_date_str:
        try:
            due_date = timezone.datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            # If date is invalid, use default based on payment method
            if payment_method == 'CREDIT':
                due_date = timezone.now().date() + timedelta(days=30)
            else:
                # For non-credit invoices, due immediately or within a short period
                due_date = timezone.now().date() + timedelta(days=7)  # 7 days for non-credit
    else:
        # No due date provided, set default based on payment method
        if payment_method == 'CREDIT':
            due_date = timezone.now().date() + timedelta(days=30)
        else:
            # For non-credit invoices, due immediately or within a short period
            due_date = timezone.now().date() + timedelta(days=7)  # 7 days for non-credit

    return {
        'store': store,
        'customer': customer,
        'payment_method': payment_method,
        'currency': post_data.get('currency', 'UGX'),
        'discount_amount': Decimal(post_data.get('discount_amount', '0')),
        'notes': post_data.get('notes', ''),
        'due_date': due_date,  # This is now ALWAYS set
    }


def create_sale_item_from_data(sale, item_data):
    """Create sale item from data"""
    item_type = item_data.get('item_type', 'PRODUCT')

    if item_type == 'PRODUCT':
        product = Product.objects.get(id=item_data['product_id'])
        service = None
    else:
        product = None
        service = Service.objects.get(id=item_data['service_id'])

    SaleItem.objects.create(
        sale=sale,
        item_type=item_type,
        product=product,
        service=service,
        quantity=Decimal(str(item_data['quantity'])),
        unit_price=Decimal(str(item_data['unit_price'])),
        tax_rate=item_data.get('tax_rate', 'A'),
        discount=Decimal(str(item_data.get('discount', 0))),
    )


def validate_stock_for_items(store, items_data):
    """Validate stock availability for product items"""
    errors = []

    # Check if store allows inventory management
    if not store.allows_inventory:
        return errors  # Skip stock validation if store doesn't manage inventory

    for item_data in items_data:
        if item_data.get('item_type') != 'PRODUCT':
            continue

        try:
            product = Product.objects.get(id=item_data['product_id'])
            stock = Stock.objects.filter(
                product=product,
                store=store
            ).first()

            if not stock:
                errors.append(f'No stock for {product.name}')
                continue

            required_qty = Decimal(str(item_data['quantity']))
            if stock.quantity < required_qty:
                errors.append(
                    f'Insufficient stock for {product.name}. '
                    f'Available: {stock.quantity}, Required: {required_qty}'
                )

        except Product.DoesNotExist:
            errors.append(f'Product not found')

    return errors


def validate_receipt_stock(receipt):
    """Validate stock for receipt before completion"""
    errors = []

    # Check if store allows inventory management
    if not receipt.store.allows_inventory:
        return errors

    for item in receipt.items.filter(item_type='PRODUCT'):
        if not item.product:
            continue

        stock = Stock.objects.filter(
            product=item.product,
            store=receipt.store
        ).first()

        if not stock or stock.quantity < item.quantity:
            errors.append(
                f'Insufficient stock for {item.product.name}'
            )

    return errors


def deduct_stock_for_item(item):
    """Deduct stock for a sale item"""
    if item.item_type != 'PRODUCT' or not item.product:
        return

    # Check if store allows inventory management
    if not item.sale.store.allows_inventory:
        logger.info(f"Store {item.sale.store.name} does not allow inventory management. Skipping stock deduction.")
        return

    stock = Stock.objects.select_for_update().get(
        product=item.product,
        store=item.sale.store
    )

    stock.quantity -= item.quantity
    stock.save()

    # Create stock movement
    from inventory.models import StockMovement
    StockMovement.objects.create(
        product=item.product,
        store=item.sale.store,
        movement_type='SALE',
        quantity=item.quantity,
        reference=item.sale.document_number,
        unit_price=item.unit_price,
        total_value=item.total_price,
        created_by=item.sale.created_by
    )