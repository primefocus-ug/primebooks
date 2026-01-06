# sales/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.db.models import Q, Sum, Max, F
from django.db import transaction
from django.utils import timezone
from django.template.loader import render_to_string
from django_tenants.utils import tenant_context
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email as django_validate_email
from django.core.mail import EmailMessage
from django.conf import settings
from weasyprint import HTML, CSS
from decimal import Decimal
import json
import logging
from datetime import datetime, timedelta

from stores.utils import validate_store_access, get_user_accessible_stores
from .models import Sale, SaleItem, Payment
from inventory.models import Product, Stock, Service, StockMovement
from customers.models import Customer
from stores.models import Store

logger = logging.getLogger(__name__)


# ==================== HELPER FUNCTIONS ====================
def get_current_tenant(request):
    """Get current tenant from request"""
    return getattr(request, 'tenant', None)


def get_user_stores(user, company):
    """Get stores accessible by user"""
    return get_user_accessible_stores(user).filter(
        company=company,
        is_active=True
    )


# ==================== QUICK POS VIEW ====================
@login_required
@permission_required("sales.add_sale", raise_exception=True)
def quick_sale_view(request):
    """
    Lightning-fast POS interface with keyboard shortcuts,
    barcode scanner, offline mode, and receipt printing.
    """
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('dashboard:home')

    with tenant_context(company):
        try:
            user = request.user
            stores = get_user_stores(user, company)

            if not stores.exists():
                return render(request, 'sales/quick_sale.html', {
                    'stores': stores,
                    'no_stores': True,
                    'error_message': 'No active stores found. Please create a store first.',
                    'company': company,
                })

            # Get user's default store
            default_store = None
            if hasattr(user, 'default_store') and user.default_store:
                default_store = user.default_store
            else:
                default_store = stores.first()

            context = {
                'company': company,
                'default_store': default_store,
                'stores': stores,
                'page_title': 'Quick Sale',
                'payment_methods': Sale.PAYMENT_METHODS,
            }

            return render(request, 'sales/quick_sale.html', context)

        except Exception as e:
            logger.error(f"Error loading quick sale view: {str(e)}", exc_info=True)
            messages.error(request, f'Error loading Quick POS: {str(e)}')
            return redirect('dashboard:home')


# ==================== SEARCH ITEMS API ====================
@login_required
@permission_required("sales.view_sale", raise_exception=True)
@require_http_methods(["GET"])
def search_items_api(request):
    """
    Search for products and services for the current tenant.
    Supports barcode scanning and offline caching.
    Tenant-aware and store-specific.
    """
    company = get_current_tenant(request)
    if not company:
        return JsonResponse({
            'success': False,
            'error': 'No company context found'
        }, status=403)

    with tenant_context(company):
        try:
            # Get search parameters
            query = request.GET.get('q', '').strip()
            store_id = request.GET.get('store_id')
            item_type = request.GET.get('item_type', 'all').upper()
            limit = int(request.GET.get('limit', 20))

            # Validate store
            if not store_id:
                return JsonResponse({
                    'success': False,
                    'error': 'Store ID is required'
                }, status=400)

            try:
                store = Store.objects.get(id=store_id, company=company, is_active=True)
            except Store.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Store not found or inactive'
                }, status=404)

            # Validate store access
            try:
                validate_store_access(request.user, store, action='view', raise_exception=True)
            except PermissionDenied as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                }, status=403)

            items = []

            # Search Products
            if item_type in ['ALL', 'PRODUCT']:
                products = Product.objects.filter(
                    company=company,
                    is_active=True
                ).select_related('category', 'unit_of_measure')

                # Apply search filter
                if query:
                    products = products.filter(
                        Q(name__icontains=query) |
                        Q(code__icontains=query) |
                        Q(barcode__icontains=query) |
                        Q(sku__icontains=query)
                    )

                # Get stock for the specific store
                for product in products[:limit]:
                    try:
                        # Get stock for this specific store
                        stock = Stock.objects.filter(
                            product=product,
                            store=store
                        ).first()

                        available_stock = stock.quantity if stock else 0
                        minimum_stock = stock.minimum_stock if stock else 10

                        items.append({
                            'id': product.id,
                            'name': product.name,
                            'code': product.code or '',
                            'barcode': product.barcode or '',
                            'sku': product.sku or '',
                            'item_type': 'PRODUCT',
                            'final_price': float(product.selling_price),
                            'original_price': float(product.selling_price),
                            'tax_rate': float(product.tax_rate) if product.tax_rate else 18.0,
                            'tax_code': product.tax_code or 'A',
                            'unit_of_measure': product.unit_of_measure.abbreviation if product.unit_of_measure else 'pcs',
                            'discount_percentage': 0,
                            'stock': {
                                'available': float(available_stock),
                                'unit': product.unit_of_measure.abbreviation if product.unit_of_measure else 'pcs',
                                'minimum_stock': minimum_stock
                            }
                        })
                    except Exception as e:
                        logger.error(f"Error getting stock for product {product.id}: {str(e)}")
                        continue

            # Search Services
            if item_type in ['ALL', 'SERVICE']:
                services = Service.objects.filter(
                    company=company,
                    is_active=True
                )

                # Apply search filter
                if query:
                    services = services.filter(
                        Q(name__icontains=query) |
                        Q(code__icontains=query) |
                        Q(description__icontains=query)
                    )

                for service in services[:limit]:
                    items.append({
                        'id': service.id,
                        'name': service.name,
                        'code': service.code or '',
                        'barcode': '',
                        'item_type': 'SERVICE',
                        'final_price': float(service.price),
                        'original_price': float(service.price),
                        'tax_rate': float(service.tax_rate) if service.tax_rate else 18.0,
                        'tax_code': service.tax_code or 'A',
                        'unit_of_measure': 'service',
                        'discount_percentage': 0,
                        'stock': None
                    })

            return JsonResponse({
                'success': True,
                'items': items[:limit],
                'total': len(items),
                'query': query,
                'store_id': store_id
            })

        except Exception as e:
            logger.error(f"Error searching items: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': f'Search failed: {str(e)}'
            }, status=500)


# ==================== CUSTOMER SEARCH API ====================
@login_required
@permission_required("sales.view_sale", raise_exception=True)
@require_http_methods(["GET"])
def customer_search_api(request):
    """
    Search customers for the current tenant.
    Store-specific and tenant-aware.
    """
    company = get_current_tenant(request)
    if not company:
        return JsonResponse([], safe=False)

    with tenant_context(company):
        try:
            query = request.GET.get('q', '').strip()
            store_id = request.GET.get('store_id')

            if not query or len(query) < 2:
                return JsonResponse([], safe=False)

            # Validate store if provided
            if store_id:
                try:
                    store = Store.objects.get(id=store_id, company=company, is_active=True)
                    validate_store_access(request.user, store, action='view', raise_exception=True)
                except (Store.DoesNotExist, PermissionDenied):
                    return JsonResponse({
                        'success': False,
                        'error': 'Invalid store or access denied'
                    }, status=403)

            # Base query - filter by tenant and store
            customers = Customer.objects.filter(
                store=store,
                is_active=True
            )

            # Filter by store if provided
            if store_id:
                customers = customers.filter(store_id=store_id)

            # Search filter
            customers = customers.filter(
                Q(name__icontains=query) |
                Q(phone__icontains=query) |
                Q(email__icontains=query) |
                Q(tin__icontains=query)
            ).select_related('store')[:10]

            # Serialize customer data
            customer_data = []
            for customer in customers:
                data = {
                    'id': customer.id,
                    'name': customer.name,
                    'phone': customer.phone or '',
                    'email': customer.email or '',
                    'tin': customer.tin or '',
                    'customer_type': customer.customer_type or 'INDIVIDUAL',
                    'store_id': customer.store_id,
                    'store_name': customer.store.name if customer.store else '',
                }

                # Add credit info if customer has credit enabled
                if hasattr(customer, 'allow_credit') and customer.allow_credit:
                    try:
                        data['credit_info'] = {
                            'allow_credit': customer.allow_credit,
                            'credit_limit': float(customer.credit_limit or 0),
                            'credit_balance': float(customer.get_credit_balance()),
                            'credit_available': float(customer.get_available_credit()),
                            'credit_status': customer.get_credit_status(),
                            'has_overdue': customer.has_overdue_invoices(),
                            'overdue_amount': float(customer.get_overdue_amount()),
                        }
                    except Exception as e:
                        logger.error(f"Error getting credit info for customer {customer.id}: {str(e)}")

                customer_data.append(data)

            return JsonResponse(customer_data, safe=False)

        except Exception as e:
            logger.error(f"Error searching customers: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)


# ==================== CREATE SALE API (Quick POS) ====================
@login_required
@permission_required("sales.add_sale", raise_exception=True)
@require_http_methods(["POST"])
def create_sale_api(request):
    """
    Create a new sale for the current tenant.
    Supports both online and offline (synced) sales.
    Handles Quick POS sales.
    """
    company = get_current_tenant(request)
    if not company:
        return JsonResponse({
            'success': False,
            'error': 'No company context found'
        }, status=403)

    with tenant_context(company):
        try:
            # Parse request data
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST.dict()

            # Check if this is an offline sale being synced
            is_offline_sale = data.get('offline_sale', False)
            offline_timestamp = data.get('offline_timestamp')

            # Determine if we should defer EFRIS sync
            # Default to True for safety, can be overridden by request
            defer_efris_sync_flag = data.get('defer_efris_sync', True)

            # Validate required fields
            store_id = data.get('store')
            if not store_id:
                return JsonResponse({
                    'success': False,
                    'error': 'Store is required'
                }, status=400)

            # Get store and verify it belongs to tenant
            try:
                store = Store.objects.get(id=store_id, company=company, is_active=True)
            except Store.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Store not found or inactive'
                }, status=404)

            # Validate store access
            try:
                validate_store_access(request.user, store, action='change', raise_exception=True)
            except PermissionDenied as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                }, status=403)

            # Check if store allows sales
            if not store.allows_sales:
                return JsonResponse({
                    'success': False,
                    'error': f"Store '{store.name}' does not allow sales"
                }, status=400)

            # Parse items data
            items_data_str = data.get('items_data', '[]')
            if isinstance(items_data_str, str):
                items_data = json.loads(items_data_str)
            else:
                items_data = items_data_str

            if not items_data:
                return JsonResponse({
                    'success': False,
                    'error': 'No items in cart'
                }, status=400)

            # Get customer if provided
            customer = None
            customer_id = data.get('customer')
            if customer_id:
                try:
                    customer = Customer.objects.get(
                        id=customer_id,
                        company=company,
                        store=store,
                        is_active=True
                    )
                except Customer.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'error': 'Customer not found'
                    }, status=404)

            # Validate payment method for credit sales
            payment_method = data.get('payment_method', 'CASH')
            if payment_method == 'CREDIT':
                if not customer:
                    return JsonResponse({
                        'success': False,
                        'error': 'Customer is required for credit sales'
                    }, status=400)

                if not customer.allow_credit:
                    return JsonResponse({
                        'success': False,
                        'error': 'Customer is not authorized for credit purchases'
                    }, status=400)

            # Start transaction
            with transaction.atomic():
                # Determine document type
                document_type = data.get('document_type', 'RECEIPT')

                # For Quick POS, default to RECEIPT unless specified
                if data.get('quick_sale', False):
                    document_type = 'RECEIPT'

                # Create sale
                sale = Sale.objects.create(
                    company=company,
                    store=store,
                    customer=customer,
                    document_type=document_type,
                    payment_method=payment_method,
                    payment_status='PAID' if payment_method != 'CREDIT' else 'PENDING',
                    subtotal_amount=Decimal(data.get('subtotal_amount', 0)),
                    tax_amount=Decimal(data.get('tax_amount', 0)),
                    discount_amount=Decimal(data.get('discount_amount', 0)),
                    total_amount=Decimal(data.get('total_amount', 0)),
                    currency=data.get('currency', 'UGX'),
                    created_by=request.user,
                    notes=data.get('notes', ''),
                    status='COMPLETED',  # Quick sales are immediately completed
                    is_quick_sale=data.get('quick_sale', False),
                    offline_sale=is_offline_sale,
                )

                # Set offline timestamp if applicable
                if is_offline_sale and offline_timestamp:
                    try:
                        sale.created_at = datetime.fromisoformat(offline_timestamp)
                        sale.save()
                    except:
                        pass

                # Create sale items and validate/update stock
                for item_data in items_data:
                    item_type = item_data.get('item_type', 'PRODUCT')

                    if item_type == 'PRODUCT':
                        try:
                            product = Product.objects.get(
                                id=item_data['product_id'],
                                company=company,
                                is_active=True
                            )
                        except Product.DoesNotExist:
                            raise ValidationError(f"Product not found")

                        # Check stock availability (only if store manages inventory)
                        if store.allows_inventory:
                            stock = Stock.objects.filter(
                                product=product,
                                store=store
                            ).select_for_update().first()

                            if not stock:
                                raise ValidationError(
                                    f"No stock record for {product.name} in {store.name}"
                                )

                            if stock.quantity < item_data['quantity']:
                                raise ValidationError(
                                    f"Insufficient stock for {product.name}. "
                                    f"Available: {stock.quantity}, "
                                    f"Required: {item_data['quantity']}"
                                )

                        # Create sale item
                        sale_item = SaleItem.objects.create(
                            sale=sale,
                            product=product,
                            item_type='PRODUCT',
                            item_name=product.name,
                            quantity=Decimal(str(item_data['quantity'])),
                            unit_price=Decimal(str(item_data['unit_price'])),
                            tax_rate=item_data.get('tax_rate', 'A'),
                            tax_code=item_data.get('tax_code', 'A'),
                            discount=Decimal(str(item_data.get('discount_amount', 0))),
                        )

                        # Calculate total
                        sale_item.total_price = (sale_item.unit_price * sale_item.quantity) - sale_item.discount
                        sale_item.save()

                        # Update stock (only if store manages inventory)
                        if store.allows_inventory:
                            stock.quantity = F('quantity') - item_data['quantity']
                            stock.save()
                            stock.refresh_from_db()

                            # Create stock movement WITH DEFERRED SYNC
                            StockMovement.objects.create(
                                company=company,
                                store=store,
                                product=product,
                                movement_type='SALE',
                                quantity=-Decimal(str(item_data['quantity'])),
                                reference_number=sale.document_number,
                                unit_price=Decimal(str(item_data['unit_price'])),
                                total_value=sale_item.total_price,
                                notes=f"Sale #{sale.document_number}",
                                created_by=request.user,
                                defer_efris_sync=defer_efris_sync_flag  # ← DEFER SYNC UNTIL FISCALIZATION
                            )

                    elif item_type == 'SERVICE':
                        try:
                            service = Service.objects.get(
                                id=item_data['service_id'],
                                company=company,
                                is_active=True
                            )
                        except Service.DoesNotExist:
                            raise ValidationError(f"Service not found")

                        # Create sale item
                        sale_item = SaleItem.objects.create(
                            sale=sale,
                            service=service,
                            item_type='SERVICE',
                            item_name=service.name,
                            quantity=Decimal(str(item_data['quantity'])),
                            unit_price=Decimal(str(item_data['unit_price'])),
                            tax_rate=item_data.get('tax_rate', 'A'),
                            tax_code=item_data.get('tax_code', 'A'),
                            discount=Decimal(str(item_data.get('discount_amount', 0))),
                        )

                        # Calculate total
                        sale_item.total_price = (sale_item.unit_price * sale_item.quantity) - sale_item.discount
                        sale_item.save()

                # Update sale totals
                sale.update_totals()

                # Create payment record for non-credit sales
                if payment_method != 'CREDIT':
                    Payment.objects.create(
                        sale=sale,
                        store=store,
                        amount=sale.total_amount,
                        payment_method=payment_method,
                        is_confirmed=True,
                        confirmed_at=timezone.now(),
                        created_by=request.user,
                        payment_type='FULL'
                    )

                # Auto-fiscalize if enabled (EFRIS)
                try:
                    if hasattr(store, 'effective_efris_config'):
                        store_config = store.effective_efris_config
                        if store_config.get('enabled', False) and store_config.get('auto_fiscalize_sales', False):
                            # Queue for fiscalization
                            from .tasks import fiscalize_invoice_async
                            fiscalize_invoice_async.delay(sale.id, user_id=request.user.pk)
                            logger.info(f"Queued sale {sale.document_number} for auto-fiscalization")

                            # Note: After fiscalization completes, you should update
                            # the StockMovement's defer_efris_sync to False and sync
                except Exception as e:
                    logger.error(f"Auto-fiscalization check failed for sale {sale.id}: {e}")

            # Return success response
            response_data = {
                'success': True,
                'sale_id': sale.id,
                'sale_number': sale.document_number,
                'total_amount': float(sale.total_amount),
                'message': 'Sale completed successfully',
                'receipt_url': f'/sales/{sale.id}/receipt/',
                'deferred_efris_sync': defer_efris_sync_flag,  # Optional: inform frontend
            }

            return JsonResponse(response_data)

        except ValidationError as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            logger.error(f"Error creating sale: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': f'Failed to create sale: {str(e)}'
            }, status=500)

# ==================== RECEIPT VIEW ====================
@login_required
@permission_required("sales.view_sale", raise_exception=True)
def sale_receipt_view(request, sale_id):
    """
    Display receipt for a completed sale.
    Tenant-aware and store-specific.
    """
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('sales:sales_list')

    with tenant_context(company):
        try:
            # Get sale and verify it belongs to tenant
            sale = get_object_or_404(
                Sale.objects.select_related('store', 'customer', 'created_by'),
                id=sale_id,
                company=company
            )

            # Validate store access
            try:
                validate_store_access(request.user, sale.store, action='view', raise_exception=True)
            except PermissionDenied as e:
                messages.error(request, str(e))
                return redirect('sales:sales_list')

            # Get sale items
            sale_items = sale.items.select_related('product', 'service').all()

            context = {
                'company': company,
                'sale': sale,
                'sale_items': sale_items,
                'page_title': f'Receipt - {sale.document_number}',
            }

            return render(request, 'sales/receipt.html', context)

        except Exception as e:
            logger.error(f"Error loading receipt: {str(e)}", exc_info=True)
            messages.error(request, 'Error loading receipt')
            return redirect('sales:sales_list')


# ==================== RECENT CUSTOMERS API ====================
@login_required
@permission_required("sales.view_sale", raise_exception=True)
@require_http_methods(["GET"])
def recent_customers_api(request):
    """
    Get recent customers for the current tenant and store.
    """
    company = get_current_tenant(request)
    if not company:
        return JsonResponse({
            'success': False,
            'error': 'No company context found'
        }, status=403)

    with tenant_context(company):
        try:
            store_id = request.GET.get('store_id')

            # Validate store if provided
            if store_id:
                try:
                    store = Store.objects.get(id=store_id, company=company, is_active=True)
                    validate_store_access(request.user, store, action='view', raise_exception=True)
                except (Store.DoesNotExist, PermissionDenied):
                    return JsonResponse({
                        'success': False,
                        'error': 'Invalid store or access denied'
                    }, status=403)

            # Get recent customers who made purchases
            recent_customers_query = Customer.objects.filter(
                company=company,
                is_active=True
            ).select_related('store')

            # Filter by store if provided
            if store_id:
                recent_customers_query = recent_customers_query.filter(store_id=store_id)

            # Get customers with their last purchase from sales
            recent_customers = recent_customers_query.annotate(
                last_purchase=Max('sales__created_at')
            ).filter(
                last_purchase__isnull=False
            ).order_by('-last_purchase')[:10]

            customers_data = []
            for customer in recent_customers:
                customers_data.append({
                    'id': customer.id,
                    'name': customer.name,
                    'phone': customer.phone or '',
                    'email': customer.email or '',
                    'tin': customer.tin or '',
                    'store_id': customer.store_id,
                    'last_purchase': customer.last_purchase.isoformat() if customer.last_purchase else None
                })

            return JsonResponse({
                'success': True,
                'customers': customers_data
            })

        except Exception as e:
            logger.error(f"Error loading recent customers: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)


# ==================== EMAIL DRAFT (for offline drafts) ====================
@login_required
@require_POST
def email_draft(request):
    """Email a draft to customer"""
    company = get_current_tenant(request)
    if not company:
        return JsonResponse({'success': False, 'error': 'No company context'})

    with tenant_context(company):
        try:
            # Parse draft data
            draft_json = request.POST.get('draft_data', '{}')
            draft_data = json.loads(draft_json)

            # Get email details
            to_email = request.POST.get('to_email', '').strip()
            subject = request.POST.get('subject', '').strip()
            message = request.POST.get('message', '').strip()

            # Validate
            if not all([draft_data, to_email, subject]):
                return JsonResponse({
                    'success': False,
                    'error': 'Missing required fields'
                })

            # Validate email format
            try:
                django_validate_email(to_email)
            except ValidationError:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid email address'
                })

            # Parse dates from ISO format
            if 'createdAt' in draft_data:
                draft_data['createdAt'] = datetime.fromisoformat(
                    draft_data['createdAt'].replace('Z', '+00:00')
                )
            if 'updatedAt' in draft_data:
                draft_data['updatedAt'] = datetime.fromisoformat(
                    draft_data['updatedAt'].replace('Z', '+00:00')
                )

            # Prepare context for template
            context = {
                'draft': draft_data,
                'company': company,
            }

            # Render HTML template
            html_content = render_to_string(
                'sales/draft_email_template.html',
                context
            )

            # Generate PDF from HTML
            pdf_file = HTML(string=html_content).write_pdf()

            # Create email
            email = EmailMessage(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to_email],
                reply_to=[settings.DEFAULT_FROM_EMAIL]
            )

            # Attach PDF
            pdf_filename = f"draft_{draft_data.get('name', 'document').replace(' ', '_')}.pdf"
            email.attach(pdf_filename, pdf_file, 'application/pdf')

            # Send email
            email.send(fail_silently=False)

            return JsonResponse({
                'success': True,
                'message': f'Draft successfully sent to {to_email}'
            })

        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid draft data format'
            })
        except Exception as e:
            logger.error(f"Error sending draft email: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': f'Failed to send email: {str(e)}'
            })