from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q, Sum, Count, Avg, F
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from datetime import timedelta, datetime
import logging
from django.template.loader import render_to_string
from weasyprint import HTML
from django.http import HttpResponse

from .models import Invoice, InvoicePayment
from sales.models import Sale, SaleItem, Payment
from customers.models import Customer
from inventory.models import Product, Service, Stock
from stores.utils import get_user_accessible_stores, validate_store_access

logger = logging.getLogger(__name__)


@login_required
def invoice_list(request):
    """List all invoices with filtering and search"""
    store = get_user_accessible_stores(request.user)

    if not store:
        messages.error(request, "You don't have access to any store")
        return redirect('user_dashboard')

    # Validate store access
    try:
        validate_store_access(request.user, store, 'view', raise_exception=True)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('user_dashboard')

    # Get filter parameters
    status_filter = request.GET.get('status', '')
    payment_status = request.GET.get('payment_status', '')
    search_query = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    customer_filter = request.GET.get('customer', '')

    # Base queryset - FIXED: Use sale relationships
    invoices = Invoice.objects.filter(
        store=store
    ).select_related(
        'sale',
        'sale__customer',
        'sale__created_by'
    ).order_by('-created_at')

    # Apply filters
    if status_filter:
        invoices = invoices.filter(sale__status=status_filter)

    if payment_status:
        invoices = invoices.filter(sale__payment_status=payment_status)

    if search_query:
        invoices = invoices.filter(
            Q(sale__document_number__icontains=search_query) |
            Q(sale__customer__name__icontains=search_query) |
            Q(fiscal_document_number__icontains=search_query)
        )

    if date_from:
        invoices = invoices.filter(sale__created_at__date__gte=date_from)

    if date_to:
        invoices = invoices.filter(sale__created_at__date__lte=date_to)

    if customer_filter:
        invoices = invoices.filter(sale__customer_id=customer_filter)

    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(invoices, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Statistics - FIXED: Use sale relationships
    stats = {
        'total_invoices': invoices.count(),
        'draft_count': invoices.filter(sale__status='DRAFT').count(),
        'pending_count': invoices.filter(sale__status='PENDING_PAYMENT').count(),
        'paid_count': invoices.filter(sale__status='PAID').count(),
        'overdue_count': invoices.filter(
            sale__payment_status='OVERDUE'
        ).count(),
        'total_amount': invoices.aggregate(
            total=Sum('sale__total_amount')
        )['total'] or Decimal('0'),
        'outstanding_amount': invoices.filter(
            sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
        ).aggregate(
            total=Sum('sale__total_amount')
        )['total'] or Decimal('0'),
    }

    # Get customers for filter
    customers = Customer.objects.filter(
        sales__store=store
    ).distinct().order_by('name')

    context = {
        'page_obj': page_obj,
        'invoices': page_obj.object_list,
        'stats': stats,
        'customers': customers,
        'status_filter': status_filter,
        'payment_status': payment_status,
        'search_query': search_query,
        'date_from': date_from,
        'date_to': date_to,
        'customer_filter': customer_filter,
        'store': store,
    }

    return render(request, 'invoices/invoice_list.html', context)


@login_required
def invoice_create(request):
    """Create a new invoice (draft)"""
    store = get_user_accessible_stores(request.user)

    # If get_user_store returns a queryset, get the first one
    if hasattr(store, 'first'):
        store = store.first()
    if not store:
        messages.error(request, "You don't have access to any store")
        return redirect('user_dashboard')

    try:
        validate_store_access(request.user, store, 'create', raise_exception=True)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('invoice:invoice_lists')

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get form data
                customer_id = request.POST.get('customer')
                due_date = request.POST.get('due_date')
                terms = request.POST.get('terms', '')
                purchase_order = request.POST.get('purchase_order', '')
                notes = request.POST.get('notes', '')

                # Validate customer
                customer = None
                if customer_id:
                    customer = Customer.objects.get(id=customer_id)

                # Create sale with INVOICE document type
                sale = Sale.objects.create(
                    store=store,
                    created_by=request.user,
                    customer=customer,
                    document_type='INVOICE',
                    payment_method='CREDIT',
                    status='DRAFT',
                    payment_status='PENDING',
                    due_date=due_date or (timezone.now().date() + timedelta(days=30)),
                    notes=notes,
                    currency='UGX',
                    transaction_type='SALE',
                )

                # Process items
                item_count = int(request.POST.get('item_count', 0))

                for i in range(item_count):
                    item_type = request.POST.get(f'item_type_{i}')
                    item_id = request.POST.get(f'item_id_{i}')

                    if not item_id:
                        continue

                    quantity = int(request.POST.get(f'quantity_{i}', 1))
                    unit_price = Decimal(request.POST.get(f'unit_price_{i}', 0))
                    discount = Decimal(request.POST.get(f'discount_{i}', 0))
                    tax_rate = request.POST.get(f'tax_rate_{i}', 'A')
                    description = request.POST.get(f'description_{i}', '')

                    if item_type == 'PRODUCT':
                        product = Product.objects.get(id=item_id)
                        SaleItem.objects.create(
                            sale=sale,
                            item_type='PRODUCT',
                            product=product,
                            quantity=quantity,
                            unit_price=unit_price,
                            discount=discount,
                            tax_rate=tax_rate,
                            description=description or product.name,
                        )
                    elif item_type == 'SERVICE':
                        service = Service.objects.get(id=item_id)
                        SaleItem.objects.create(
                            sale=sale,
                            item_type='SERVICE',
                            service=service,
                            quantity=quantity,
                            unit_price=unit_price,
                            discount=discount,
                            tax_rate=tax_rate,
                            description=description or service.name,
                        )

                # Update sale totals
                sale.update_totals()

                # Create invoice detail
                invoice = Invoice.objects.create(
                    sale=sale,
                    store=store,
                    terms=terms,
                    purchase_order=purchase_order,
                    created_by=request.user,
                    operator_name=request.user.get_full_name() or str(request.user),
                )

                messages.success(request, f'Invoice {sale.document_number} created successfully')
                return redirect('invoice:invoice_detail', pk=invoice.pk)

        except Exception as e:
            logger.error(f"Error creating invoice: {e}", exc_info=True)
            messages.error(request, f"Error creating invoice: {str(e)}")

    # GET request - show form
    customers = Customer.objects.filter(
        is_active=True
    ).order_by('name')

    # Get products and services for this store
    products = Product.objects.filter(
        is_active=True
    ).select_related('category').values(
        'id', 'name', 'sku', 'selling_price', 'tax_rate', 'unit_of_measure'
    )

    services = Service.objects.filter(
        is_active=True
    ).values(
        'id', 'name', 'code', 'tax_rate', 'unit_of_measure'
    )

    # Convert to list for template
    products_list = list(products)
    services_list = list(services)

    context = {
        'customers': customers,
        'products': products_list,
        'services': services_list,
        'store': store,
        'default_due_date': (timezone.now().date() + timedelta(days=30)).strftime('%Y-%m-%d'),
    }

    return render(request, 'invoices/invoice_create.html', context)


@login_required
def invoice_detail(request, pk):
    """View invoice details"""
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            'sale',
            'sale__customer',
            'sale__created_by',
            'store'
        ),
        pk=pk
    )

    # Validate store access
    try:
        validate_store_access(request.user, invoice.store, 'view', raise_exception=True)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('invoice:invoice_lists')

    # Get stock availability
    stock_availability = invoice.stock_availability

    # Get payments
    payments = invoice.sale.payments.filter(
        is_voided=False
    ).order_by('-created_at')

    # Check permissions
    can_edit, edit_message = invoice.can_edit()
    can_cancel, cancel_message = invoice.can_cancel()
    can_pay, pay_message = invoice.can_mark_as_paid()

    context = {
        'invoice': invoice,
        'sale': invoice.sale,
        'items': invoice.sale.items.select_related('product', 'service'),
        'stock_availability': stock_availability,
        'payments': payments,
        'can_edit': can_edit,
        'edit_message': edit_message,
        'can_cancel': can_cancel,
        'cancel_message': cancel_message,
        'can_pay': can_pay,
        'pay_message': pay_message,
        'can_send': invoice.can_send,
    }

    return render(request, 'invoices/invoice_detail.html', context)


@login_required
def invoice_edit(request, pk):
    """Edit draft invoice"""
    invoice = get_object_or_404(Invoice, pk=pk)

    # Validate store access
    try:
        validate_store_access(request.user, invoice.store, 'edit', raise_exception=True)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('invoices:invoice_detail', pk=pk)

    # Check if can edit
    can_edit, message = invoice.can_edit()
    if not can_edit:
        messages.error(request, message)
        return redirect('invoices:invoice_detail', pk=pk)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                sale = invoice.sale

                # Update sale fields
                customer_id = request.POST.get('customer')
                if customer_id:
                    sale.customer = Customer.objects.get(id=customer_id)

                sale.due_date = request.POST.get('due_date')
                sale.notes = request.POST.get('notes', '')

                # Update invoice fields
                invoice.terms = request.POST.get('terms', '')
                invoice.purchase_order = request.POST.get('purchase_order', '')

                # Delete existing items
                sale.items.all().delete()

                # Add new items
                item_count = int(request.POST.get('item_count', 0))

                for i in range(item_count):
                    item_type = request.POST.get(f'item_type_{i}')
                    item_id = request.POST.get(f'item_id_{i}')

                    if not item_id:
                        continue

                    quantity = int(request.POST.get(f'quantity_{i}', 1))
                    unit_price = Decimal(request.POST.get(f'unit_price_{i}', 0))
                    discount = Decimal(request.POST.get(f'discount_{i}', 0))
                    tax_rate = request.POST.get(f'tax_rate_{i}', 'A')
                    description = request.POST.get(f'description_{i}', '')

                    if item_type == 'PRODUCT':
                        product = Product.objects.get(id=item_id)
                        SaleItem.objects.create(
                            sale=sale,
                            item_type='PRODUCT',
                            product=product,
                            quantity=quantity,
                            unit_price=unit_price,
                            discount=discount,
                            tax_rate=tax_rate,
                            description=description or product.name,
                        )
                    elif item_type == 'SERVICE':
                        service = Service.objects.get(id=item_id)
                        SaleItem.objects.create(
                            sale=sale,
                            item_type='SERVICE',
                            service=service,
                            quantity=quantity,
                            unit_price=unit_price,
                            discount=discount,
                            tax_rate=tax_rate,
                            description=description or service.name,
                        )

                # Update totals
                sale.update_totals()
                sale.save()
                invoice.save()

                messages.success(request, f'Invoice {sale.document_number} updated successfully')
                return redirect('invoices:invoice_detail', pk=invoice.pk)

        except Exception as e:
            logger.error(f"Error updating invoice: {e}", exc_info=True)
            messages.error(request, f"Error updating invoice: {str(e)}")

    # GET request
    customers = Customer.objects.filter(is_active=True).order_by('name')
    products = Product.objects.filter(store=invoice.store, is_active=True).values(
        'id', 'name', 'sku', 'selling_price', 'tax_rate', 'unit_of_measure'
    )
    services = Service.objects.filter(store=invoice.store, is_active=True).values(
        'id', 'name', 'code', 'price', 'tax_rate', 'unit_of_measure'
    )

    context = {
        'invoice': invoice,
        'sale': invoice.sale,
        'items': invoice.sale.items.all(),
        'customers': customers,
        'products': list(products),
        'services': list(services),
    }

    return render(request, 'invoices/invoice_edit.html', context)


@login_required
def invoice_mark_sent(request, pk):
    """Mark invoice as sent"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    invoice = get_object_or_404(Invoice, pk=pk)

    try:
        validate_store_access(request.user, invoice.store, 'edit', raise_exception=True)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=403)

    try:
        invoice.mark_as_sent(user=request.user)
        messages.success(request, f'Invoice {invoice.sale.document_number} marked as sent')
        return JsonResponse({'success': True, 'message': 'Invoice marked as sent'})
    except Exception as e:
        logger.error(f"Error marking invoice as sent: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def invoice_mark_paid(request, pk):
    """Mark invoice as paid"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    invoice = get_object_or_404(Invoice, pk=pk)

    try:
        validate_store_access(request.user, invoice.store, 'edit', raise_exception=True)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=403)

    try:
        payment_method = request.POST.get('payment_method', 'CASH')
        transaction_reference = request.POST.get('transaction_reference', '')

        invoice.mark_as_paid(
            user=request.user,
            payment_method=payment_method,
            transaction_reference=transaction_reference
        )

        messages.success(request, f'Invoice {invoice.sale.document_number} marked as paid. Stock deducted.')
        return JsonResponse({
            'success': True,
            'message': 'Invoice marked as paid',
            'redirect_url': f'/invoices/{invoice.pk}/'
        })
    except Exception as e:
        logger.error(f"Error marking invoice as paid: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def invoice_cancel(request, pk):
    """Cancel an unpaid invoice"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    invoice = get_object_or_404(Invoice, pk=pk)

    try:
        validate_store_access(request.user, invoice.store, 'delete', raise_exception=True)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=403)

    try:
        reason = request.POST.get('reason', 'Cancelled by user')
        invoice.cancel_invoice(reason=reason, user=request.user)

        messages.success(request, f'Invoice {invoice.sale.document_number} cancelled')
        return JsonResponse({
            'success': True,
            'message': 'Invoice cancelled',
            'redirect_url': '/invoices/'
        })
    except Exception as e:
        logger.error(f"Error cancelling invoice: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def invoice_delete(request, pk):
    """Delete a draft invoice"""
    if request.method != 'POST':
        messages.error(request, "Invalid request method")
        return redirect('invoices:invoice_list')

    invoice = get_object_or_404(Invoice, pk=pk)

    try:
        validate_store_access(request.user, invoice.store, 'delete', raise_exception=True)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('invoices:invoice_detail', pk=pk)

    # Only allow deletion of draft invoices
    if invoice.sale.status != 'DRAFT':
        messages.error(request, "Only draft invoices can be deleted")
        return redirect('invoices:invoice_detail', pk=pk)

    try:
        document_number = invoice.sale.document_number
        invoice.sale.delete()  # Cascade will delete invoice
        messages.success(request, f'Invoice {document_number} deleted successfully')
        return redirect('invoices:invoice_list')
    except Exception as e:
        logger.error(f"Error deleting invoice: {e}", exc_info=True)
        messages.error(request, f"Error deleting invoice: {str(e)}")
        return redirect('invoices:invoice_detail', pk=pk)


# API Endpoints for AJAX

@login_required
def get_product_details(request, product_id):
    """Get product details for invoice form"""
    try:
        product = Product.objects.get(id=product_id)
        store = get_user_accessible_stores(request.user)

        # Get stock
        stock = Stock.objects.filter(product=product, store=store).first()
        available_stock = stock.quantity if stock else 0

        return JsonResponse({
            'success': True,
            'product': {
                'id': product.id,
                'name': product.name,
                'sku': product.sku,
                'selling_price': str(product.selling_price),
                'tax_rate': product.tax_rate,
                'available_stock': available_stock,
                'unit_of_measure': product.unit_of_measure,
            }
        })
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def get_service_details(request, service_id):
    """Get service details for invoice form"""
    try:
        service = Service.objects.get(id=service_id)

        return JsonResponse({
            'success': True,
            'service': {
                'id': service.id,
                'name': service.name,
                'code': service.code,
                'price': str(service.price),
                'tax_rate': service.tax_rate,
                'unit_of_measure': service.unit_of_measure or '207',
            }
        })
    except Service.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Service not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def search_products(request):
    """Search products for invoice"""
    query = request.GET.get('q', '')
    store = get_user_accessible_stores(request.user)

    products = Product.objects.filter(
        store=store,
        is_active=True
    ).filter(
        Q(name__icontains=query) | Q(sku__icontains=query)
    )[:10]

    results = [{
        'id': p.id,
        'name': p.name,
        'sku': p.sku,
        'price': str(p.selling_price),
        'type': 'PRODUCT'
    } for p in products]

    return JsonResponse({'results': results})


@login_required
def search_services(request):
    """Search services for invoice"""
    query = request.GET.get('q', '')
    store = get_user_accessible_stores(request.user)

    services = Service.objects.filter(
        store=store,
        is_active=True
    ).filter(
        Q(name__icontains=query) | Q(code__icontains=query)
    )[:10]

    results = [{
        'id': s.id,
        'name': s.name,
        'code': s.code,
        'price': str(s.price),
        'type': 'SERVICE'
    } for s in services]

    return JsonResponse({'results': results})



@login_required
def invoice_preview(request, pk):
    """Preview invoice before finalizing"""
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            'sale',
            'sale__customer',
            'sale__created_by',
            'store',
            'store__company'
        ),
        pk=pk
    )

    # Validate store access
    try:
        validate_store_access(request.user, invoice.store, 'view', raise_exception=True)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('invoices:invoice_list')

    context = {
        'invoice': invoice,
        'sale': invoice.sale,
        'items': invoice.sale.items.select_related('product', 'service'),
        'company': invoice.store.company,
        'store': invoice.store,
        'is_preview': True,
    }

    return render(request, 'invoices/invoice_preview.html', context)


@login_required
def invoice_print(request, pk):
    """Print-friendly invoice view"""
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            'sale',
            'sale__customer',
            'sale__created_by',
            'store',
            'store__company'
        ),
        pk=pk
    )

    # Validate store access
    try:
        validate_store_access(request.user, invoice.store, 'view', raise_exception=True)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('invoices:invoice_list')

    context = {
        'invoice': invoice,
        'sale': invoice.sale,
        'items': invoice.sale.items.select_related('product', 'service'),
        'company': invoice.store.company,
        'store': invoice.store,
        'is_print': True,
    }

    return render(request, 'invoices/invoice_print.html', context)


@login_required
def invoice_download_pdf(request, pk):
    """Download invoice as PDF"""
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            'sale',
            'sale__customer',
            'sale__created_by',
            'store',
            'store__company'
        ),
        pk=pk
    )

    # Validate store access
    try:
        validate_store_access(request.user, invoice.store, 'view', raise_exception=True)
    except Exception as e:
        return HttpResponse('Access denied', status=403)

    context = {
        'invoice': invoice,
        'sale': invoice.sale,
        'items': invoice.sale.items.select_related('product', 'service'),
        'company': invoice.store.company,
        'store': invoice.store,
    }

    # Render HTML template
    html_string = render_to_string('invoices/invoice_pdf_template.html', context)

    # Generate PDF
    html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
    pdf = html.write_pdf()

    # Create response
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="invoice_{invoice.sale.document_number}.pdf"'

    return response