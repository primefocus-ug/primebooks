import uuid
from stores.mixins import StoreQuerysetMixin
from channels.layers import get_channel_layer
from django.urls import reverse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.generic import ListView, DetailView
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q, Sum, Count, Avg, F, Min, Max
from django.db import transaction, connection, IntegrityError
from django.utils import timezone
from django.core.mail import EmailMessage
from django.http import HttpResponseServerError
from django.conf import settings
from django.core.exceptions import ValidationError, PermissionDenied
from decimal import Decimal, InvalidOperation
from django.core.paginator import Paginator
import json
from django.views.decorators.http import require_GET
import csv
from django.template.loader import render_to_string, get_template
import xlsxwriter
from io import BytesIO
from datetime import datetime, timedelta
import logging
from django.core.cache import cache
from tenancy.utils import tenant_context_safe
from .models import Sale, SaleItem, Payment, Cart, CartItem, Receipt
from .forms import (
    SaleForm, SaleItemForm, PaymentForm, CartForm, QuickSaleForm,
    SaleSearchForm, RefundForm, ReceiptForm, BulkActionForm,
    SaleItemFormSet, PaymentFormSet
)
from inventory.models import Product, Stock, StockMovement,Service
from customers.models import Customer
from stores.models import Store
from stores.utils import validate_store_access, get_user_accessible_stores
from company.models import Company

logger = logging.getLogger(__name__)

def get_current_tenant(request):
    """Get current tenant from request"""
    return getattr(request, 'tenant', None)


def get_user_company(user):
    """Get user's company"""
    return getattr(user, 'company', None)


def handle_export(request, action):
    """Handle export requests"""
    try:
        export_format = action.replace('export_', '')

        # Get selected sales or all filtered sales
        selected_sales_json = request.POST.get('selected_sales')

        if selected_sales_json:
            try:
                selected_ids = json.loads(selected_sales_json)
                sales = Sale.objects.filter(id__in=selected_ids)
            except json.JSONDecodeError:
                sales = get_filtered_sales(request)
        else:
            sales = get_filtered_sales(request)

        # Apply user's store access filter
        accessible_stores = get_user_accessible_stores(request.user)
        sales = sales.filter(store__in=accessible_stores)

        # Call the appropriate export function
        if export_format == 'csv':
            return export_sales_csv(sales)
        elif export_format == 'excel':
            return export_sales_excel(sales)
        elif export_format == 'pdf':
            return export_sales_pdf(sales)
        else:
            messages.error(request, 'Invalid export format')
            return redirect('sales:sales_list')

    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        messages.error(request, f'Export failed: {str(e)}')
        return redirect('sales:sales_list')


def get_filtered_sales(request):
    """Get sales based on current filters"""
    accessible_stores = get_user_accessible_stores(request.user)
    queryset = Sale.objects.filter(store__in=accessible_stores)

    # Apply filters from GET parameters
    search = request.GET.get('search') or request.POST.get('search')
    if search:
        queryset = queryset.filter(
            Q(document_number__icontains=search) |
            Q(transaction_id__icontains=search) |
            Q(customer__name__icontains=search) |
            Q(customer__phone__icontains=search)
        )

    store = request.GET.get('store') or request.POST.get('store')
    if store:
        queryset = queryset.filter(store_id=store)

    transaction_type = request.GET.get('transaction_type') or request.POST.get('transaction_type')
    if transaction_type:
        queryset = queryset.filter(transaction_type=transaction_type)

    payment_method = request.GET.get('payment_method') or request.POST.get('payment_method')
    if payment_method:
        queryset = queryset.filter(payment_method=payment_method)

    date_from = request.GET.get('date_from') or request.POST.get('date_from')
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)

    date_to = request.GET.get('date_to') or request.POST.get('date_to')
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    return queryset.select_related('store', 'customer', 'created_by').order_by('-created_at')


def export_sales_csv(sales):
    """Export sales to CSV"""
    response = HttpResponse(content_type='text/csv')
    response[
        'Content-Disposition'] = f'attachment; filename="sales_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Document Number', 'Date', 'Time', 'Customer', 'Store',
        'Payment Method', 'Subtotal', 'Tax', 'Discount', 'Total',
        'Status', 'Fiscalized'
    ])

    for sale in sales:
        writer.writerow([
            sale.document_number,
            sale.created_at.strftime('%Y-%m-%d'),
            sale.created_at.strftime('%H:%M:%S'),
            sale.customer.name if sale.customer else 'Walk-in',
            sale.store.name,
            sale.get_payment_method_display(),
            float(sale.subtotal),
            float(sale.tax_amount),
            float(sale.discount_amount),
            float(sale.total_amount),
            sale.get_status_display(),
            'Yes' if sale.is_fiscalized else 'No'
        ])

    return response


def export_sales_excel(sales):
    """Export sales to Excel"""
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet('Sales Export')

    # Define formats
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#366092',
        'color': 'white',
        'border': 1
    })

    currency_format = workbook.add_format({'num_format': '#,##0.00'})
    date_format = workbook.add_format({'num_format': 'yyyy-mm-dd'})
    time_format = workbook.add_format({'num_format': 'hh:mm:ss'})

    # Headers
    headers = [
        'Document Number', 'Date', 'Time', 'Customer', 'Store',
        'Payment Method', 'Subtotal', 'Tax', 'Discount', 'Total',
        'Status', 'Fiscalized'
    ]

    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)

    # Data
    for row, sale in enumerate(sales, 1):
        worksheet.write(row, 0, sale.document_number)
        worksheet.write(row, 1, sale.created_at.strftime('%Y-%m-%d'), date_format)
        worksheet.write(row, 2, sale.created_at.strftime('%H:%M:%S'), time_format)
        worksheet.write(row, 3, sale.customer.name if sale.customer else 'Walk-in')
        worksheet.write(row, 4, sale.store.name)
        worksheet.write(row, 5, sale.get_payment_method_display())
        worksheet.write(row, 6, float(sale.subtotal), currency_format)
        worksheet.write(row, 7, float(sale.tax_amount), currency_format)
        worksheet.write(row, 8, float(sale.discount_amount), currency_format)
        worksheet.write(row, 9, float(sale.total_amount), currency_format)
        worksheet.write(row, 10, sale.get_status_display())
        worksheet.write(row, 11, 'Yes' if sale.is_fiscalized else 'No')

    # Auto-fit columns
    worksheet.set_column('A:L', 15)

    workbook.close()
    output.seek(0)

    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response[
        'Content-Disposition'] = f'attachment; filename="sales_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

    return response


def export_sales_pdf(sales):
    """Export sales to PDF"""
    from django.template.loader import get_template
    from xhtml2pdf import pisa

    template = get_template('sales/sales_export_pdf.html')
    context = {
        'sales': sales,
        'export_date': timezone.now(),
        'total_sales': sales.count(),
        'total_amount': sales.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    }

    html = template.render(context)
    response = HttpResponse(content_type='application/pdf')
    response[
        'Content-Disposition'] = f'attachment; filename="sales_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)

    if pisa_status.err:
        return HttpResponse('PDF generation error', status=500)

    return response

@login_required
@require_POST
def create_customer_ajax(request):
    """Create customer within tenant context and associate with store"""
    try:
        company = get_current_tenant(request)
        if not company:
            return JsonResponse({
                'success': False,
                'error': 'No company context found'
            })

        with tenant_context_safe(company):
            # ✅ ADD: Get and validate store_id
            store_id = request.POST.get('store_id')

            if not store_id:
                return JsonResponse({
                    'success': False,
                    'error': 'Store selection required. Please select a branch first.'
                })

            # ✅ ADD: Validate store exists and user has access
            try:
                store = Store.objects.get(
                    id=store_id,
                    company=company,
                    is_active=True
                )
                validate_store_access(request.user, store, action='create', raise_exception=True)
            except Store.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid store selected'
                })
            except PermissionDenied:
                return JsonResponse({
                    'success': False,
                    'error': 'Access denied to create customers in this store'
                })

            # Get form data
            name = request.POST.get('name', '').strip()
            phone = request.POST.get('phone', '').strip()
            email = request.POST.get('email', '').strip()
            address = request.POST.get('address', '').strip()
            customer_type = request.POST.get('customer_type', 'INDIVIDUAL').strip()
            tin = request.POST.get('tin', '').strip()
            nin = request.POST.get('nin', '').strip()
            brn = request.POST.get('brn', '').strip()
            from_efris = request.POST.get('from_efris', 'false') == 'true'

            logger.info(f"Creating customer: {name}, {phone} for tenant {company.schema_name}, store {store.name}")

            # Validation
            if not name or not phone:
                return JsonResponse({
                    'success': False,
                    'error': 'Name and phone are required'
                })

            # ✅ UPDATE: Check for duplicate phone in same store (not globally)
            if Customer.objects.filter(phone=phone, store=store).exists():
                return JsonResponse({
                    'success': False,
                    'error': f'Customer with this phone number already exists in {store.name}'
                })

            # Create customer with selected store
            customer = Customer.objects.create(
                name=name,
                phone=phone,
                store=store,  # ✅ Use selected store, not first available
                email=email or None,
                physical_address=address or None,
                customer_type=customer_type,
                tin=tin or None,
                nin=nin or None,
                brn=brn or None,
                efris_customer_type='2' if customer_type == 'BUSINESS' else '1',
                created_by=request.user
            )

            logger.info(f"✅ Customer created: {customer.name} (ID: {customer.id}) in store {store.name}")

            # Get credit info for response
            customer.update_credit_balance()

            return JsonResponse({
                'success': True,
                'customer': {
                    'id': customer.id,
                    'name': customer.name,
                    'phone': customer.phone,
                    'email': customer.email or '',
                    'address': customer.physical_address or '',
                    'customer_type': customer.customer_type,
                    'tin': customer.tin or '',
                    'nin': customer.nin or '',
                    'brn': customer.brn or '',
                    'store_id': customer.store_id,  # ✅ ADD
                    'store_name': customer.store.name,  # ✅ ADD

                    # ✅ ADD: Include credit info in response
                    'credit_info': {
                        'allow_credit': customer.allow_credit,
                        'credit_limit': float(customer.credit_limit),
                        'credit_balance': float(customer.credit_balance),
                        'credit_available': float(customer.credit_available),
                        'credit_status': customer.credit_status,
                        'has_overdue': customer.has_overdue_invoices,
                        'overdue_amount': float(customer.overdue_amount),
                        'can_purchase_credit': customer.can_purchase_on_credit[0],
                        'credit_message': customer.can_purchase_on_credit[1],
                    }
                }
            })

    except Exception as e:
        logger.error(f"❌ Error creating customer: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Failed to create customer: {str(e)}'
        })


@login_required
def search_products_and_services(request):
    """Combined search for products and services with pagination"""
    try:
        company = get_current_tenant(request)
        if not company:
            return JsonResponse({'error': 'No company context'}, status=403)

        with tenant_context_safe(company):
            query = request.GET.get('q', '').strip()
            store_id = request.GET.get('store_id')
            item_type = request.GET.get('item_type', 'all')

            # ✅ NEW: Get pagination parameters
            try:
                page = int(request.GET.get('page', 1))
                if page < 1:
                    page = 1
            except (ValueError, TypeError):
                page = 1

            limit = 50  # ✅ Fixed at 50 items per page

            # Validate store access
            store = None
            if store_id:
                try:
                    store_id = int(store_id)
                    store = Store.objects.filter(
                        id=store_id,
                        company=company,
                        is_active=True
                    ).first()

                    if not store:
                        return JsonResponse({
                            'error': 'Access denied to store'
                        }, status=403)

                except (ValueError, Store.DoesNotExist):
                    return JsonResponse({
                        'error': 'Invalid store'
                    }, status=400)

            items_data = []

            # Search products
            if item_type in ['product', 'all']:
                products_query = Product.objects.filter(
                    is_active=True,
                )

                if query:
                    products_query = products_query.filter(
                        Q(name__icontains=query) |
                        Q(sku__icontains=query) |
                        Q(barcode__icontains=query)
                    )

                if store:
                    products_query = products_query.filter(
                        store_inventory__store=store,
                        store_inventory__quantity__gte=0
                    )

                # ✅ Get total count BEFORE slicing
                products_count = products_query.count()

                products = products_query.select_related('category', 'supplier')

                for product in products:
                    stock_info = None
                    if store:
                        try:
                            stock = product.store_inventory.get(store=store)
                            stock_info = {
                                'available': float(stock.quantity),
                                'unit': product.unit_of_measure or 'pcs',
                                'store_id': store.id
                            }
                        except Stock.DoesNotExist:
                            stock_info = {
                                'available': 0,
                                'unit': product.unit_of_measure or 'pcs'
                            }

                    items_data.append({
                        'id': product.id,
                        'name': product.name,
                        'code': product.sku or '',
                        'price': float(product.selling_price or 0),
                        'final_price': float(product.selling_price or 0),
                        'discount_percentage': float(getattr(product, 'discount_percentage', 0)),
                        'tax_rate': getattr(product, 'tax_rate', 'A'),
                        'unit_of_measure': product.unit_of_measure or 'pcs',
                        'stock': stock_info,
                        'category': product.category.name if product.category else '',
                        'item_type': 'PRODUCT',
                        'has_stock': stock_info['available'] > 0 if stock_info else True,
                    })

            # Search services
            if item_type in ['service', 'all']:
                services_query = Service.objects.filter(
                    is_active=True,
                )

                if query:
                    services_query = services_query.filter(
                        Q(name__icontains=query) |
                        Q(code__icontains=query) |
                        Q(description__icontains=query)
                    )

                # ✅ Get total count BEFORE slicing
                services_count = services_query.count()

                services = services_query.select_related('category')

                for service in services:
                    items_data.append({
                        'id': service.id,
                        'name': service.name,
                        'code': service.code or '',
                        'price': float(service.unit_price or 0),
                        'final_price': float(service.unit_price or 0),
                        'tax_rate': getattr(service, 'tax_rate', 'A'),
                        'unit_of_measure': service.unit_of_measure or 'unit',
                        'category': service.category.name if service.category else '',
                        'description': service.description or '',
                        'item_type': 'SERVICE',
                        'stock': None,
                        'has_stock': True,
                    })

            # ✅ Calculate pagination
            total_items = len(items_data)
            start_index = (page - 1) * limit
            end_index = start_index + limit

            # Slice the items for current page
            paginated_items = items_data[start_index:end_index]

            # ✅ Calculate pagination metadata
            total_pages = (total_items + limit - 1) // limit  # Ceiling division
            has_next = page < total_pages
            has_previous = page > 1

            return JsonResponse({
                'items': paginated_items,
                'pagination': {
                    'total': total_items,
                    'page': page,
                    'limit': limit,
                    'total_pages': total_pages,
                    'has_next': has_next,
                    'has_previous': has_previous,
                    'start_index': start_index + 1 if paginated_items else 0,
                    'end_index': min(end_index, total_items)
                }
            })

    except Exception as e:
        logger.error(f"Error in combined search: {e}", exc_info=True)
        return JsonResponse({
            'error': 'Search failed',
            'message': str(e)
        }, status=500)


@login_required
def search_services(request):
    """
    AJAX endpoint for searching services (similar to product search)
    """
    try:
        from stores.utils import validate_store_access

        query = request.GET.get('q', '').strip()
        store_id = request.GET.get('store_id')

        if len(query) < 2:
            return JsonResponse({'services': []})

        # Validate store access
        store = None
        if store_id:
            try:
                store_id = int(store_id)
                store = Store.objects.get(id=store_id)

                # Validate store access using utility function
                try:
                    validate_store_access(request.user, store, action='view', raise_exception=True)
                except PermissionDenied:
                    return JsonResponse({'error': 'Access denied to store'}, status=403)

            except (ValueError, Store.DoesNotExist):
                return JsonResponse({'error': 'Invalid store'}, status=400)

        # Import Service model
        from inventory.models import Service

        # Base service query
        services = Service.objects.filter(
            is_active=True
        ).filter(
            Q(name__icontains=query) |
            Q(code__icontains=query) |
            Q(description__icontains=query)
        ).select_related('category')

        services = services.distinct()[:20]

        service_data = []
        for service in services:
            efris_data = {}
            if hasattr(service, 'get_efris_data'):
                try:
                    efris_data = {
                        'efris_service_name': service.efris_service_name if hasattr(service,
                                                                                    'efris_service_name') else None,
                        'efris_service_code': service.efris_service_code if hasattr(service,
                                                                                    'efris_service_code') else None,
                        'efris_uploaded': getattr(service, 'efris_is_uploaded', False),
                    }
                except Exception as e:
                    logger.warning(f"Error getting EFRIS data for service {service.id}: {e}")

            service_data.append({
                'id': service.id,
                'name': service.name,
                'code': service.code or '',
                'price': float(service.unit_price or 0),
                'final_price': float(service.unit_price or 0),
                'tax_rate': getattr(service, 'tax_rate', 'A'),
                'unit_of_measure': service.unit_of_measure or '207',  # Hours
                'category': service.category.name if service.category else '',
                'description': service.description or '',
                'efris': efris_data,
                'item_type': 'SERVICE',
            })

        return JsonResponse({'services': service_data})

    except Exception as e:
        logger.error(f"Error in service search: {e}")
        return JsonResponse({'error': 'Search failed'}, status=500)


class SalesListView(StoreQuerysetMixin,LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Enhanced sales list with advanced filtering, pagination, and credit invoice support"""
    model = Sale
    template_name = 'sales/sales_list.html'
    context_object_name = 'sales'
    paginate_by = 25
    permission_required = 'sales.view_sale'

    def post(self, request, *args, **kwargs):
        """Handle POST requests for exports and bulk actions"""
        action = request.POST.get('action', '')

        if action.startswith('export_'):
            return self.handle_export(request, action)
        else:
            # Handle other bulk actions
            return bulk_actions(request)

    def handle_export(self, request, action):
        """Handle export requests"""
        try:
            export_format = action.replace('export_', '')

            # Get selected sales or all filtered sales
            selected_sales_json = request.POST.get('selected_sales')

            if selected_sales_json:
                try:
                    selected_ids = json.loads(selected_sales_json)
                    sales = Sale.objects.filter(id__in=selected_ids)
                except json.JSONDecodeError:
                    sales = self.get_export_queryset(request)
            else:
                sales = self.get_export_queryset(request)

            # Apply user's store access filter
            accessible_stores = get_user_accessible_stores(request.user)
            sales = sales.filter(store__in=accessible_stores).select_related(
                'store', 'customer', 'created_by'
            ).prefetch_related('items', 'payments').order_by('-created_at')

            # Call the appropriate export function
            if export_format == 'csv':
                return self.export_to_csv(sales)
            elif export_format == 'excel':
                return self.export_to_excel(sales)
            elif export_format == 'pdf':
                return self.export_to_pdf(sales)
            else:
                messages.error(request, 'Invalid export format')
                return redirect('sales:sales_list')

        except Exception as e:
            logger.error(f"Export error: {e}", exc_info=True)
            messages.error(request, f'Export failed: {str(e)}')
            return redirect('sales:sales_list')

    def get_export_queryset(self, request):
        """Get sales based on current filters from POST data"""
        accessible_stores = get_user_accessible_stores(request.user)
        queryset = Sale.objects.filter(store__in=accessible_stores)

        # Apply filters from POST parameters (same as GET)
        search = request.POST.get('search', '')
        if search:
            queryset = queryset.filter(
                Q(document_number__icontains=search) |
                Q(transaction_id__icontains=search) |
                Q(customer__name__icontains=search) |
                Q(customer__phone__icontains=search) |
                Q(efris_invoice_number__icontains=search)
            )

        store = request.POST.get('store')
        if store:
            queryset = queryset.filter(store_id=store)

        transaction_type = request.POST.get('transaction_type')
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)

        payment_method = request.POST.get('payment_method')
        if payment_method:
            queryset = queryset.filter(payment_method=payment_method)

        document_type = request.POST.get('document_type')
        if document_type:
            queryset = queryset.filter(document_type=document_type)

        date_from = request.POST.get('date_from')
        if date_from:
            try:
                queryset = queryset.filter(created_at__date__gte=date_from)
            except:
                pass

        date_to = request.POST.get('date_to')
        if date_to:
            try:
                queryset = queryset.filter(created_at__date__lte=date_to)
            except:
                pass

        min_amount = request.POST.get('min_amount')
        if min_amount:
            try:
                queryset = queryset.filter(total_amount__gte=Decimal(min_amount))
            except:
                pass

        max_amount = request.POST.get('max_amount')
        if max_amount:
            try:
                queryset = queryset.filter(total_amount__lte=Decimal(max_amount))
            except:
                pass

        is_fiscalized = request.POST.get('is_fiscalized')
        if is_fiscalized:
            queryset = queryset.filter(is_fiscalized=is_fiscalized == '1')

        payment_status = request.POST.get('payment_status')
        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)

        status = request.POST.get('status')
        if status:
            queryset = queryset.filter(status=status)

        return queryset

    def export_to_csv(self, sales):
        """Export sales to CSV"""
        response = HttpResponse(content_type='text/csv')
        response[
            'Content-Disposition'] = f'attachment; filename="sales_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Document Number', 'Document Type', 'Date', 'Time', 'Customer', 'Phone',
            'Store', 'Payment Method', 'Subtotal', 'Tax', 'Discount', 'Total',
            'Payment Status', 'Status', 'Fiscalized', 'EFRIS Invoice'
        ])

        for sale in sales:
            writer.writerow([
                sale.document_number or '',
                sale.get_document_type_display(),
                sale.created_at.strftime('%Y-%m-%d'),
                sale.created_at.strftime('%H:%M:%S'),
                sale.customer.name if sale.customer else 'Walk-in',
                sale.customer.phone if sale.customer else '',
                sale.store.name,
                sale.get_payment_method_display(),
                float(sale.subtotal),
                float(sale.tax_amount),
                float(sale.discount_amount),
                float(sale.total_amount),
                sale.get_payment_status_display(),
                sale.get_status_display(),
                'Yes' if sale.is_fiscalized else 'No',
                sale.efris_invoice_number or ''
            ])

        return response

    def export_to_excel(self, sales):
        """Export sales to Excel"""
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Sales Export')

        # Define formats
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#366092',
            'color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })

        currency_format = workbook.add_format({'num_format': '#,##0.00'})
        date_format = workbook.add_format({'num_format': 'yyyy-mm-dd'})
        time_format = workbook.add_format({'num_format': 'hh:mm:ss'})

        # Headers
        headers = [
            'Document Number', 'Document Type', 'Date', 'Time', 'Customer', 'Phone',
            'Store', 'Payment Method', 'Subtotal', 'Tax', 'Discount', 'Total',
            'Payment Status', 'Status', 'Fiscalized', 'EFRIS Invoice'
        ]

        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)

        # Data
        for row, sale in enumerate(sales, 1):
            worksheet.write(row, 0, sale.document_number or '')
            worksheet.write(row, 1, sale.get_document_type_display())
            worksheet.write(row, 2, sale.created_at.strftime('%Y-%m-%d'), date_format)
            worksheet.write(row, 3, sale.created_at.strftime('%H:%M:%S'), time_format)
            worksheet.write(row, 4, sale.customer.name if sale.customer else 'Walk-in')
            worksheet.write(row, 5, sale.customer.phone if sale.customer else '')
            worksheet.write(row, 6, sale.store.name)
            worksheet.write(row, 7, sale.get_payment_method_display())
            worksheet.write(row, 8, float(sale.subtotal), currency_format)
            worksheet.write(row, 9, float(sale.tax_amount), currency_format)
            worksheet.write(row, 10, float(sale.discount_amount), currency_format)
            worksheet.write(row, 11, float(sale.total_amount), currency_format)
            worksheet.write(row, 12, sale.get_payment_status_display())
            worksheet.write(row, 13, sale.get_status_display())
            worksheet.write(row, 14, 'Yes' if sale.is_fiscalized else 'No')
            worksheet.write(row, 15, sale.efris_invoice_number or '')

        # Auto-fit columns
        worksheet.set_column('A:P', 15)
        worksheet.set_column('E:E', 25)  # Customer name wider

        workbook.close()
        output.seek(0)

        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response[
            'Content-Disposition'] = f'attachment; filename="sales_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

        return response

    def export_to_pdf(self, sales):
        """Export sales to PDF"""
        try:
            from xhtml2pdf import pisa
        except ImportError:
            messages.error(self.request, 'PDF export requires xhtml2pdf package. Please contact administrator.')
            return redirect('sales:sales_list')

        # Calculate totals
        total_amount = sales.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_tax = sales.aggregate(Sum('tax_amount'))['tax_amount__sum'] or 0
        total_discount = sales.aggregate(Sum('discount_amount'))['discount_amount__sum'] or 0

        context = {
            'sales': sales[:100],  # Limit to first 100 for PDF
            'export_date': timezone.now(),
            'total_sales': sales.count(),
            'total_amount': total_amount,
            'total_tax': total_tax,
            'total_discount': total_discount,
            'user': self.request.user,
        }

        template = get_template('sales/sales_export_pdf.html')
        html = template.render(context)

        response = HttpResponse(content_type='application/pdf')
        response[
            'Content-Disposition'] = f'attachment; filename="sales_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'

        pisa_status = pisa.CreatePDF(html, dest=response)

        if pisa_status.err:
            messages.error(self.request, 'Error generating PDF')
            return redirect('sales:sales_list')

        return response

    def get_queryset(self):
        # Get accessible stores for this user
        accessible_stores = get_user_accessible_stores(self.request.user)

        # Filter sales by accessible stores
        queryset = Sale.objects.filter(
            store__in=accessible_stores
        ).select_related(
            'store', 'customer', 'created_by'
        ).prefetch_related('items', 'payments')

        form = SaleSearchForm(self.request.GET)
        if form.is_valid():
            search = form.cleaned_data.get('search')
            if search:
                # Updated to use document_number instead of invoice_number
                queryset = queryset.filter(
                    Q(document_number__icontains=search) |
                    Q(transaction_id__icontains=search) |
                    Q(customer__name__icontains=search) |
                    Q(customer__phone__icontains=search) |
                    Q(efris_invoice_number__icontains=search) |
                    Q(store__name__icontains=search)
                )

            store = form.cleaned_data.get('store')
            if store:
                # Ensure the selected store is accessible to the user
                if store in accessible_stores:
                    queryset = queryset.filter(store=store)
                else:
                    # If user tries to filter by a store they don't have access to,
                    # ignore the filter but show a warning
                    from django.contrib import messages
                    messages.warning(self.request,
                                     f"You don't have access to store '{store.name}'. Filter ignored.")

            transaction_type = form.cleaned_data.get('transaction_type')
            if transaction_type:
                queryset = queryset.filter(transaction_type=transaction_type)

            payment_method = form.cleaned_data.get('payment_method')
            if payment_method:
                queryset = queryset.filter(payment_method=payment_method)

            document_type = form.cleaned_data.get('document_type')
            if document_type:
                queryset = queryset.filter(document_type=document_type)

            date_from = form.cleaned_data.get('date_from')
            if date_from:
                queryset = queryset.filter(created_at__date__gte=date_from)

            date_to = form.cleaned_data.get('date_to')
            if date_to:
                queryset = queryset.filter(created_at__date__lte=date_to)

            min_amount = form.cleaned_data.get('min_amount')
            if min_amount:
                queryset = queryset.filter(total_amount__gte=min_amount)

            max_amount = form.cleaned_data.get('max_amount')
            if max_amount:
                queryset = queryset.filter(total_amount__lte=max_amount)

            is_fiscalized = form.cleaned_data.get('is_fiscalized')
            if is_fiscalized:
                queryset = queryset.filter(is_fiscalized=is_fiscalized == '1')

            payment_status = form.cleaned_data.get('payment_status')
            if payment_status:
                queryset = queryset.filter(payment_status=payment_status)

            status = form.cleaned_data.get('status')
            if status:
                queryset = queryset.filter(status=status)

            # ADD: Filter by credit status
            credit_status = form.cleaned_data.get('credit_status')
            if credit_status:
                if credit_status == 'CREDIT':
                    queryset = queryset.filter(
                        document_type='INVOICE',
                        payment_method='CREDIT'
                    )
                elif credit_status == 'OVERDUE':
                    queryset = queryset.filter(
                        document_type='INVOICE',
                        payment_status='OVERDUE'
                    )
                elif credit_status == 'OUTSTANDING':
                    queryset = queryset.filter(
                        document_type='INVOICE',
                        payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
                    )

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get accessible stores for filter dropdown
        accessible_stores = get_user_accessible_stores(self.request.user)

        # Initialize form with GET data
        search_form = SaleSearchForm(self.request.GET)

        # Limit store choices to accessible stores
        if search_form.fields.get('store'):
            search_form.fields['store'].queryset = accessible_stores

        context['search_form'] = search_form
        context['bulk_form'] = BulkActionForm()

        # Add accessible stores to context for template display
        context['accessible_stores'] = accessible_stores

        # Add EFRIS enabled flag
        context['efris_enabled'] = any(
            store.effective_efris_config.get('enabled', False)
            for store in accessible_stores
        )

        # ── Stats: ONE aggregate query replacing 12+ separate COUNT/SUM calls ──
        # Cached per store per day. Invalidated by post_save signal in cache.py.
        queryset = self.get_queryset()
        date_str = timezone.now().strftime('%Y-%m-%d')
        store_ids = '_'.join(str(s.id) for s in accessible_stores)
        stats_cache_key = f'sale_stats:{store_ids}:{date_str}'

        agg = cache.get(stats_cache_key)
        if agg is None:
            agg = queryset.aggregate(
                total_sales          = Count('id'),
                total_amount         = Sum('total_amount'),
                total_credit_amount  = Sum('total_amount',
                    filter=Q(document_type='INVOICE', payment_method='CREDIT')),
                fiscalized_count     = Count('id', filter=Q(is_fiscalized=True)),
                receipt_count        = Count('id', filter=Q(document_type='RECEIPT')),
                invoice_count        = Count('id', filter=Q(document_type='INVOICE')),
                proforma_count       = Count('id', filter=Q(document_type='PROFORMA')),
                estimate_count       = Count('id', filter=Q(document_type='ESTIMATE')),
                overdue_count        = Count('id', filter=Q(payment_status='OVERDUE')),
                overdue_amount       = Sum('total_amount', filter=Q(payment_status='OVERDUE')),
                credit_pending_count = Count('id', filter=Q(
                    document_type='INVOICE', payment_method='CREDIT',
                    payment_status__in=['PENDING', 'PARTIALLY_PAID'])),
                credit_paid_count    = Count('id', filter=Q(
                    document_type='INVOICE', payment_method='CREDIT',
                    payment_status='PAID')),
                avg_credit_amount    = Avg('total_amount', filter=Q(
                    document_type='INVOICE', payment_method='CREDIT')),
            )
            cache.set(stats_cache_key, agg, 60)  # 60-second TTL

        total_sales = agg['total_sales'] or 0

        context['stats'] = {
            'total_sales':        total_sales,
            'total_amount':       agg['total_amount'] or 0,
            'total_credit_amount':agg['total_credit_amount'] or 0,
            'fiscalized_count':   agg['fiscalized_count'] or 0,
            'receipt_count':      agg['receipt_count'] or 0,
            'invoice_count':      agg['invoice_count'] or 0,
            'proforma_count':     agg['proforma_count'] or 0,
            'estimate_count':     agg['estimate_count'] or 0,
        }

        context['credit_stats'] = {
            'total_credit_invoices': (agg['invoice_count'] or 0),
            'total_credit_amount':   agg['total_credit_amount'] or 0,
            'overdue_count':         agg['overdue_count'] or 0,
            'overdue_amount':        agg['overdue_amount'] or 0,
            'pending_count':         agg['credit_pending_count'] or 0,
            'paid_count':            agg['credit_paid_count'] or 0,
            'avg_credit_amount':     agg['avg_credit_amount'] or 0,
        }

        # Document-type distribution — one VALUES+ANNOTATE query, cached together
        doc_type_stats_key = f'sale_doc_type_stats:{store_ids}:{date_str}'
        doc_type_raw = cache.get(doc_type_stats_key)
        if doc_type_raw is None:
            doc_type_raw = list(queryset.values('document_type').annotate(
                count=Count('id'),
                total=Sum('total_amount')
            ).order_by('-count'))
            cache.set(doc_type_stats_key, doc_type_raw, 60)

        context['document_type_stats'] = [
            {
                'type': s['document_type'],
                'type_display': dict(Sale.DOCUMENT_TYPE_CHOICES).get(
                    s['document_type'], s['document_type']),
                'count': s['count'],
                'total': s['total'] or 0,
                'percentage': (s['count'] / total_sales * 100) if total_sales > 0 else 0,
            }
            for s in doc_type_raw
        ]

        # Payment-status distribution
        pay_stats_key = f'sale_pay_stats:{store_ids}:{date_str}'
        pay_stats_raw = cache.get(pay_stats_key)
        if pay_stats_raw is None:
            pay_stats_raw = list(queryset.values('payment_status').annotate(
                count=Count('id'),
                total=Sum('total_amount')
            ).order_by('-count'))
            cache.set(pay_stats_key, pay_stats_raw, 60)

        context['payment_status_stats'] = [
            {
                'status': s['payment_status'],
                'status_display': dict(Sale.PAYMENT_STATUS_CHOICES).get(
                    s['payment_status'], s['payment_status']),
                'count': s['count'],
                'total': s['total'] or 0,
            }
            for s in pay_stats_raw
        ]

        # EFRIS stats — reuse agg data, no extra query
        if agg['fiscalized_count']:
            efris_key = f'sale_efris_latest:{store_ids}'
            latest_fiscal = cache.get(efris_key)
            if latest_fiscal is None:
                latest_fiscal = (
                    queryset.filter(is_fiscalized=True)
                    .order_by('-fiscalization_time')
                    .only('id', 'document_number', 'fiscalization_time')
                    .first()
                )
                cache.set(efris_key, latest_fiscal, 120)
            context['efris_stats'] = {
                'count':        agg['fiscalized_count'],
                'total_amount': agg['total_amount'] or 0,
                'latest_fiscalized': latest_fiscal,
            }

        # Store performance — cached 2 minutes (changes less often)
        store_perf_key = f'sale_store_perf:{store_ids}:{date_str}'
        store_performance = cache.get(store_perf_key)
        if store_performance is None:
            store_performance = list(
                queryset.values('store__id', 'store__name').annotate(
                    sales_count=Count('id'),
                    total_amount=Sum('total_amount'),
                    fiscalized_count=Count('id', filter=Q(is_fiscalized=True)),
                ).order_by('-total_amount')[:10]
            )
            cache.set(store_perf_key, store_performance, 120)
        context['store_performance'] = store_performance

        # Top credit customers — cached 2 minutes
        top_cust_key = f'sale_top_cust:{store_ids}:{date_str}'
        top_credit_customers = cache.get(top_cust_key)
        if top_credit_customers is None:
            top_credit_customers = list(
                queryset.filter(
                    document_type='INVOICE', payment_method='CREDIT'
                ).values(
                    'customer__id', 'customer__name', 'customer__phone'
                ).annotate(
                    invoice_count=Count('id'),
                    total_credit=Sum('total_amount'),
                    outstanding_count=Count('id', filter=Q(
                        payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE'])),
                ).order_by('-total_credit')[:5]
            )
            cache.set(top_cust_key, top_credit_customers, 120)
        context['top_credit_customers'] = top_credit_customers

        return context

class SaleDetailView(StoreQuerysetMixin,LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """Enhanced sale detail view with comprehensive information, EFRIS integration, and credit details"""
    model = Sale
    template_name = 'sales/sales_detail.html'
    context_object_name = 'sale'
    permission_required = 'sales.view_sale'
    login_url = 'login'

    def get_object(self):
        # Use 'items' as the relation name (from SaleItem.sale ForeignKey with related_name='items')
        sale = get_object_or_404(
            Sale.objects.select_related('store', 'customer', 'created_by')
            .prefetch_related('items__product', 'items__service', 'payments', 'receipt_detail'),
            pk=self.kwargs['pk']
        )

        # Check user access to this sale using utility function
        try:
            validate_store_access(self.request.user, sale.store, action='view', raise_exception=True)
        except PermissionDenied as e:
            messages.error(self.request, str(e))
            raise

        return sale

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sale = self.object

        # Check store's EFRIS configuration
        store_config = sale.store.effective_efris_config
        efris_enabled = store_config.get('enabled', False)

        can_fiscalize = False
        fiscalization_error = None

        if efris_enabled:
            can_fiscalize, fiscalization_error = sale.can_fiscalize(self.request.user)

        fiscal_data = self._get_fiscalization_data(sale)

        # ========== FIXED PAYMENT CALCULATION ==========
        # Get total paid from CONFIRMED and NON-VOIDED payments only
        total_paid = sale.payments.filter(
            is_confirmed=True,
            is_voided=False
        ).aggregate(
            Sum('amount')
        )['amount__sum'] or Decimal('0')

        # Calculate balance with proper Decimal handling
        try:
            sale_total = Decimal(str(sale.total_amount or 0))
            total_paid_decimal = Decimal(str(total_paid))

            balance_due = max(Decimal('0'), sale_total - total_paid_decimal)
            is_paid_in_full = balance_due <= Decimal('0.01')

            # ✅ RECEIPTS are always paid (immediate payment)
            if sale.document_type == 'RECEIPT':
                is_paid_in_full = True
                balance_due = Decimal('0')

            # ✅ Non-credit INVOICES: Check if payment received
            elif sale.document_type == 'INVOICE' and sale.payment_method != 'CREDIT':
                if total_paid_decimal >= sale_total:
                    is_paid_in_full = True
                    balance_due = Decimal('0')

        except (ValueError, TypeError) as e:
            logger.error(f"Error calculating balance for sale {sale.id}: {e}")
            balance_due = Decimal('0')
            is_paid_in_full = True

        # ========== AUTO-UPDATE PAYMENT STATUS ==========
        if sale.document_type in ['RECEIPT', 'INVOICE']:
            new_payment_status = None

            if is_paid_in_full:
                new_payment_status = 'PAID'
            elif total_paid_decimal > Decimal('0'):
                new_payment_status = 'PARTIALLY_PAID'
            elif sale.due_date and sale.due_date < timezone.now().date():
                new_payment_status = 'OVERDUE'
            else:
                new_payment_status = 'PENDING'

            # Update if changed
            if new_payment_status != sale.payment_status:
                sale.payment_status = new_payment_status
                if is_paid_in_full:
                    sale.status = 'COMPLETED'
                sale.save(update_fields=['payment_status', 'status'])
                logger.info(f"✅ Updated sale {sale.id}: {sale.payment_status}")

        # Payment breakdown by method
        payments_by_method = sale.payments.filter(
            is_confirmed=True,
            is_voided=False
        ).values('payment_method').annotate(
            total=Sum('amount'),
            count=Count('id')
        ).order_by('-total')

        # Permissions
        can_refund = (
                sale.transaction_type == 'SALE' and
                not sale.is_refunded and
                self.request.user.has_perm('sales.can_process_refund')
        )

        can_void = (
                sale.transaction_type == 'SALE' and
                not sale.is_voided and
                self.request.user.has_perm('sales.can_void_sale')
        )

        receipt = getattr(sale, 'receipt_detail', None)
        invoice_detail = None
        if sale.document_type == 'INVOICE' and hasattr(sale, 'invoice_detail'):
            invoice_detail = sale.invoice_detail

        # Customer credit info
        customer_credit_info = None
        if sale.customer and sale.document_type == 'INVOICE':
            sale.customer.update_credit_balance()
            customer_credit_info = {
                'allow_credit': sale.customer.allow_credit,
                'credit_limit': sale.customer.credit_limit,
                'credit_balance': sale.customer.credit_balance,
                'credit_available': sale.customer.credit_available,
                'credit_status': sale.customer.credit_status,
                'credit_status_display': sale.customer.get_credit_status_display(),
                'has_overdue': sale.customer.has_overdue_invoices,
                'overdue_amount': sale.customer.overdue_amount,
                'outstanding_invoices_count': Sale.objects.filter(
                    customer=sale.customer,
                    document_type='INVOICE',
                    payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
                ).count()
            }

        payment_schedules = []
        if (sale.document_type == 'INVOICE' and
                sale.payment_method == 'CREDIT' and
                hasattr(sale, 'invoice_detail')):
            payment_schedules = sale.invoice_detail.payment_schedules.all()

        context.update({
            'refund_form': RefundForm(),
            'receipt_form': ReceiptForm(),
            'can_refund': can_refund,
            'can_void': can_void,
            'can_fiscalize': can_fiscalize,
            'fiscalization_error': fiscalization_error,
            'efris_enabled': efris_enabled,
            'store_config': store_config,
            'total_paid': total_paid,
            'balance_due': balance_due,
            'is_paid_in_full': is_paid_in_full,
            'receipt': receipt,
            'invoice_detail': invoice_detail,
            'customer_credit_info': customer_credit_info,
            'payment_schedules': payment_schedules,
            'payments_by_method': payments_by_method,
            'is_credit_invoice': (
                    sale.document_type == 'INVOICE' and
                    sale.payment_method == 'CREDIT'
            ),
            'requires_due_date': (
                    sale.document_type == 'INVOICE' and
                    sale.payment_method == 'CREDIT'
            ),
            **fiscal_data
        })

        return context

    def _get_fiscalization_data(self, sale):
        """Extract fiscalization data directly from sale (works for all document types)"""
        fiscal_data = {
            'invoice_fiscalized': sale.is_fiscalized,
            'fiscal_document_number': sale.efris_invoice_number,
            'fiscal_qr_code': sale.qr_code,
            'fiscal_verification_url': self._get_verification_url(
                sale.efris_invoice_number,
                sale.verification_code
            ),
            'fiscalization_time': sale.fiscalization_time,
            'efris_invoice_no': sale.efris_invoice_number,
            'efris_antifake_code': sale.verification_code,
            'verification_code': sale.verification_code,
            'is_fiscalized': sale.is_fiscalized,
        }

        # If sale has QR code URL from EFRIS, use it
        qr_code = sale.qr_code
        if qr_code and qr_code.startswith('http'):
            fiscal_data['fiscal_verification_url'] = qr_code

        return fiscal_data

    def _get_verification_url(self, invoice_no, verification_code):
        """Generate EFRIS verification URL for both test and production environments"""
        if not invoice_no or not verification_code:
            return None

        # Get store to check environment
        sale = self.object
        store_config = sale.store.effective_efris_config

        # Check if we're in test or production mode
        is_production = store_config.get('is_production', False)

        if is_production:
            # Production EFRIS URL
            base_url = "https://efris.ura.go.ug/"
        else:
            # Test EFRIS URL (from your logs)
            base_url = "https://efristest.ura.go.ug"

        # URL format from your EFRIS response
        return f"{base_url}/site_new/#/invoiceValidation?invoiceNo={invoice_no}&antiFakeCode={verification_code}"

def should_create_invoice(sale, user):
    """
    Enhanced logic to determine if an invoice should be created for this sale.
    Now uses the Sale model's EFRIS mixin methods for better decision making.
    """
    if not sale.is_completed:
        return False

    company = sale.store.company
    with tenant_context_safe(company):
        # Check company invoice creation policy
        if not getattr(company, 'auto_create_invoices', False):
            return False

        invoice_policy = getattr(company, 'invoice_required_for', 'MANUAL')

        if invoice_policy == 'MANUAL':
            return False
        elif invoice_policy == 'ALL':
            return True
        elif invoice_policy == 'B2B':
            # Use customer's EFRIS mixin method to determine business type
            if sale.customer and hasattr(sale.customer, 'get_efris_buyer_details'):
                buyer_details = sale.customer.get_efris_buyer_details()
                return buyer_details.get('buyerType') == "0"  # B2B
            return False
        elif invoice_policy == 'EFRIS_ENABLED':
            # Only create invoices if EFRIS is enabled
            return getattr(company, 'efris_enabled', False)

        return False


def create_invoice_for_sale(sale, user):
    """
    Enhanced invoice creation using Sale model's EFRIS mixins to build proper data.
    """
    from invoices.models import Invoice
    from django.core.exceptions import ValidationError

    try:
        company = sale.store.company
        with tenant_context_safe(company):

            # ========== FIXED: Check for existing InvoiceDetail ==========
            # Check if invoice already exists in InvoiceDetail model
            try:
                from sales.models import InvoiceDetail
                existing_invoice_detail = InvoiceDetail.objects.filter(sale=sale).first()
                if existing_invoice_detail:
                    logger.warning(
                        f"InvoiceDetail already exists for sale {sale.id}: {existing_invoice_detail.invoice_number}")

                    # Also check if Invoice model has a record
                    try:
                        existing_invoice = Invoice.objects.filter(sale=sale).first()
                        if existing_invoice:
                            return existing_invoice
                    except Invoice.DoesNotExist:
                        pass

                    # Create Invoice model instance if it doesn't exist
                    invoice, created = Invoice.objects.get_or_create(
                        sale=sale,
                        defaults={
                            'store': sale.store,
                            'business_type': 'B2C',
                            'operator_name': user.get_full_name() or str(user),
                            'created_by': user,
                        }
                    )
                    if created:
                        logger.info(f"Created Invoice model instance for existing InvoiceDetail")

                    return invoice
            except ImportError:
                logger.warning("InvoiceDetail model not available")
            # =============================================================

            logger.info(f"Creating invoice for sale {sale.id}")

            # Use Sale's EFRIS mixin to get proper buyer details
            business_type = 'B2C'  # Default
            if sale.customer and hasattr(sale.customer, 'get_efris_buyer_details'):
                buyer_details = sale.customer.get_efris_buyer_details()
                buyer_type = buyer_details.get('buyerType', '1')
                if buyer_type == '0':
                    business_type = 'B2B'
                elif buyer_type == '3':
                    business_type = 'B2G'

            # Use Sale's EFRIS mixin to get basic information
            efris_basic_info = sale.get_efris_basic_info() if hasattr(sale, 'get_efris_basic_info') else {}
            efris_summary = sale.get_efris_summary() if hasattr(sale, 'get_efris_summary') else {}

            # ========== SAFE CREATE: Use get_or_create to prevent duplicates ==========
            invoice, created = Invoice.objects.get_or_create(
                sale=sale,
                defaults={
                    'store': sale.store,
                    'business_type': business_type,
                    'operator_name': efris_basic_info.get('operator', user.get_full_name() or str(user)),
                    'created_by': user,
                }
            )

            if not created:
                logger.info(f"Invoice already exists for sale {sale.id}: {invoice.invoice_number}")
                return invoice
            # ===========================================================================

            logger.info(f"Created invoice {invoice.invoice_number} for sale {sale.id}")

            # Copy sale items to invoice items (only if newly created)
            try:
                from invoices.models import InvoiceItem
                for sale_item in sale.items.all():
                    # Check if item already exists (match on product OR service)
                    existing_item = InvoiceItem.objects.filter(
                        invoice=invoice,
                        product=sale_item.product,
                        service=sale_item.service,
                    ).exists()

                    if not existing_item:
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            product=sale_item.product if sale_item.item_type == 'PRODUCT' else None,
                            service=sale_item.service if sale_item.item_type == 'SERVICE' else None,
                            quantity=sale_item.quantity,
                            unit_price=sale_item.unit_price,
                            total_price=sale_item.total_price,
                            tax_amount=getattr(sale_item, 'tax_amount', 0),
                            discount_amount=getattr(sale_item, 'discount_amount', 0),
                        )
                    else:
                        item_label = sale_item.product.name if sale_item.item_type == 'PRODUCT' else (
                            sale_item.service.name if sale_item.service else 'Unknown'
                        )
                        logger.debug(f"Invoice item already exists for {item_label}")
            except ImportError:
                logger.warning("InvoiceItem model not available")

            # Auto-fiscalize if enabled and sale can be fiscalized
            if getattr(company, 'auto_fiscalize', False):
                try:
                    # Use Sale's EFRIS mixin to check if it can be fiscalized
                    can_fiscalize, reason = sale.can_fiscalize(user)
                    if can_fiscalize:
                        fiscalize_invoice_immediately(invoice, user)
                    else:
                        logger.info(f"Invoice {invoice.id} not auto-fiscalized: {reason}")
                except Exception as e:
                    logger.error(f"Immediate fiscalization failed for invoice {invoice.id}: {e}")
                    try:
                        from .tasks import fiscalize_invoice_async
                        fiscalize_invoice_async.delay(invoice.pk, user.pk)
                    except ImportError:
                        logger.warning("Celery tasks not available, skipping async fiscalization")

            return invoice

    except Exception as e:
        logger.error(f"Failed to create invoice for sale {sale.id}: {e}")
        raise


@login_required
@permission_required('sales.add_payment', raise_exception=True)
@require_POST
def add_payment(request, sale_id):
    """Record a payment for a sale"""
    sale = get_object_or_404(
        Sale.objects.select_related('store', 'customer'),
        pk=sale_id
    )

    # Check user access
    try:
        validate_store_access(request.user, sale.store, action='change', raise_exception=True)
    except PermissionDenied as e:
        messages.error(request, str(e))
        return redirect('sales:sale_detail', pk=sale_id)

    try:
        with transaction.atomic():
            # Get form data
            amount = Decimal(str(request.POST.get('amount', 0)))
            payment_method = request.POST.get('payment_method', 'CASH')
            payment_date = request.POST.get('payment_date')
            transaction_reference = request.POST.get('transaction_reference', '').strip()
            notes = request.POST.get('notes', '').strip()

            # Validate amount
            if amount <= 0:
                messages.error(request, 'Payment amount must be greater than 0')
                return redirect('sales:sale_detail', pk=sale_id)

            # Calculate outstanding balance
            total_paid = sale.payments.filter(
                is_confirmed=True,
                is_voided=False
            ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

            balance_due = sale.total_amount - total_paid

            if amount > balance_due:
                messages.error(
                    request,
                    f'Payment amount ({amount:,.2f}) exceeds outstanding balance ({balance_due:,.2f})'
                )
                return redirect('sales:sale_detail', pk=sale_id)

            # Parse payment date
            if payment_date:
                try:
                    payment_date = datetime.strptime(payment_date, '%Y-%m-%d').date()
                except ValueError:
                    payment_date = timezone.now().date()
            else:
                payment_date = timezone.now().date()

            # Create payment record
            payment = Payment.objects.create(
                sale=sale,
                store=sale.store,
                amount=amount,
                payment_method=payment_method,
                transaction_reference=transaction_reference,
                notes=notes,
                is_confirmed=True,
                confirmed_at=timezone.now(),
                created_by=request.user
            )

            # Update sale payment status
            sale.update_payment_status()

            # Log the payment
            logger.info(
                f"Payment recorded: Sale={sale.id}, Amount={amount}, "
                f"Method={payment_method}, User={request.user.id}"
            )

            # Success message
            messages.success(
                request,
                f'Payment of {amount:,.2f} UGX recorded successfully. '
                f'New balance: {sale.amount_outstanding:,.2f} UGX'
            )

            # If fully paid, show completion message
            if sale.amount_outstanding <= Decimal('0.01'):
                messages.success(request, '🎉 Sale is now fully paid!')

            return redirect('sales:sale_detail', pk=sale_id)

    except Exception as e:
        logger.error(f"Error recording payment for sale {sale_id}: {e}", exc_info=True)
        messages.error(request, f'Error recording payment: {str(e)}')
        return redirect('sales:sale_detail', pk=sale_id)

@login_required
@require_GET
def recent_customers_api(request):
    """
    API endpoint to fetch recent customers for a store with credit info
    Used in POS interface and sales forms
    """
    try:
        store_id = request.GET.get('store_id')
        limit = int(request.GET.get('limit', 10))
        search = request.GET.get('search', '').strip()

        # ✅ UPDATE: More strict store_id validation
        if not store_id:
            # Try to get store_id from session (if coming from POS)
            store_id = request.session.get('current_store_id')

            # If still no store_id, get user's accessible stores
            if not store_id:
                accessible_stores = get_user_accessible_stores(request.user)
                if accessible_stores.exists():
                    store_id = accessible_stores.first().id
                else:
                    return JsonResponse({
                        'success': False,
                        'error': 'No store available. Please select a store first.',
                        'customers': []
                    })

        # Validate store access
        try:
            store = Store.objects.get(id=store_id, is_active=True)
            validate_store_access(request.user, store, action='view', raise_exception=True)
        except Store.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Invalid store',
                'customers': []
            }, status=404)
        except PermissionDenied:
            return JsonResponse({
                'success': False,
                'error': 'Access denied to store',
                'customers': []
            }, status=403)

        # Base query for customers in this store ONLY
        customers_query = Customer.objects.filter(
            store_id=store_id,  # ✅ Explicitly filter by store
            is_active=True
        )

        # Apply search filter if provided
        if search:
            customers_query = customers_query.filter(
                Q(name__icontains=search) |
                Q(phone__icontains=search) |
                Q(email__icontains=search)
            )

        # Get recent purchases data
        from django.db.models import Subquery, OuterRef

        # Subquery to get last purchase date for each customer IN THIS STORE
        last_purchase_subquery = Sale.objects.filter(
            customer_id=OuterRef('id'),
            store_id=store_id  # ✅ Ensure we only count purchases from this store
        ).order_by('-created_at').values('created_at')[:1]

        # Subquery to get purchase count for each customer IN THIS STORE
        purchase_count_subquery = Sale.objects.filter(
            customer_id=OuterRef('id'),
            store_id=store_id  # ✅ Ensure we only count purchases from this store
        ).values('customer_id').annotate(
            count=Count('id')
        ).values('count')

        # Subquery to get total spent for each customer IN THIS STORE
        total_spent_subquery = Sale.objects.filter(
            customer_id=OuterRef('id'),
            store_id=store_id  # ✅ Ensure we only count purchases from this store
        ).values('customer_id').annotate(
            total=Sum('total_amount')
        ).values('total')

        # Annotate customers with purchase data
        customers = customers_query.annotate(
            last_purchase_date=Subquery(last_purchase_subquery),
            purchase_count=Subquery(purchase_count_subquery),
            total_spent=Subquery(total_spent_subquery)
        ).select_related('store').order_by(  # ✅ ADD: select_related
            '-last_purchase_date',  # Customers with recent purchases first
            '-created_at'  # Then newly created customers
        )[:limit]

        # Prepare response data
        customers_data = []
        for customer in customers:
            # Do not call update_credit_balance() in a list loop — it fires a
            # DB write per row. Balances are kept fresh by the periodic
            # refresh_customer_credit_balances Celery task.

            # Get EFRIS data if available
            efris_data = {}
            if hasattr(customer, 'get_efris_buyer_details'):
                try:
                    buyer_details = customer.get_efris_buyer_details()
                    efris_data = {
                        'buyer_type': buyer_details.get('buyerType', '1'),
                        'buyer_type_display': 'Business' if buyer_details.get('buyerType') == '0' else 'Individual',
                        'tin': buyer_details.get('buyerTin', ''),
                        'nin_brn': buyer_details.get('buyerNinBrn', ''),
                        'is_efris_ready': all([
                            buyer_details.get('buyerLegalName'),
                            buyer_details.get('buyerMobilePhone')
                        ])
                    }
                except Exception as e:
                    logger.debug(f"Error getting EFRIS data for customer {customer.id}: {e}")

            customer_data = {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone or '',
                'email': customer.email or '',
                'address': customer.physical_address or '',
                'customer_type': customer.customer_type or 'INDIVIDUAL',
                'tin': customer.tin or '',
                'nin': customer.nin or '',
                'brn': customer.brn or '',
                'last_purchase': customer.last_purchase_date.isoformat() if customer.last_purchase_date else None,
                'purchase_count': customer.purchase_count or 0,
                'total_spent': float(customer.total_spent or 0),
                'efris': efris_data,
                'created_at': customer.created_at.isoformat() if customer.created_at else None,
                'store_id': customer.store_id,  # ✅ ADD
                'store_name': customer.store.name if customer.store else None,  # ✅ ADD

                # Credit information
                'credit_info': {
                    'allow_credit': customer.allow_credit,
                    'credit_limit': float(customer.credit_limit) if customer.credit_limit else 0.0,
                    'credit_balance': float(customer.credit_balance) if customer.credit_balance else 0.0,
                    'credit_available': float(customer.credit_available) if customer.credit_available else 0.0,
                    'credit_status': customer.credit_status,
                    'credit_status_display': customer.get_credit_status_display(),
                    'has_overdue': customer.has_overdue_invoices,
                    'overdue_amount': float(customer.overdue_amount) if customer.overdue_amount else 0.0,
                    'can_purchase_credit': customer.can_purchase_on_credit[0] if hasattr(customer, 'can_purchase_on_credit') else False,
                    'credit_message': customer.can_purchase_on_credit[1] if hasattr(customer, 'can_purchase_on_credit') else '',
                    'credit_days': customer.credit_days if hasattr(customer, 'credit_days') else 30,
                }
            }
            customers_data.append(customer_data)

        return JsonResponse({
            'success': True,
            'customers': customers_data,
            'count': len(customers_data),
            'store': {
                'id': store.id,
                'name': store.name,
            }
        })

    except Exception as e:
        logger.error(f"Error in recent_customers_api: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while fetching customers',
            'details': str(e) if settings.DEBUG else 'Internal server error',
            'customers': []
        }, status=500)

def fiscalize_invoice_immediately(invoice, user):
    """
    Enhanced immediate fiscalization using the new EFRIS service structure.
    Now uses the InvoiceEFRISService from the invoices app.
    """
    try:
        # Import the app-specific EFRIS service
        from efris.services import EFRISInvoiceService

        # Create service instance with company context
        service = EFRISInvoiceService(invoice.store.company)
        success, message = service.fiscalize_invoice(invoice, user)

        if success:
            # Update related sale using the invoice's EFRIS mixin method
            if hasattr(invoice, 'update_sale_from_efris'):
                invoice.update_sale_from_efris()
            else:
                # Fallback to manual update
                sale = invoice.sale
                sale.efris_invoice_number = invoice.fiscal_document_number
                sale.verification_code = invoice.verification_code
                sale.is_fiscalized = True
                sale.fiscalization_time = timezone.now()
                sale.save(update_fields=[
                    'efris_invoice_number', 'verification_code',
                    'is_fiscalized', 'fiscalization_time'
                ])

            logger.info(f"Successfully fiscalized invoice {invoice.invoice_number}")
            return True
        else:
            logger.error(f"EFRIS fiscalization failed for invoice {invoice.id}: {message}")
            return False

    except ImportError as e:
        logger.error(f"EFRIS service not available: {e}")
        return False
    except Exception as e:
        logger.error(f"Fiscalization error for invoice {invoice.id}: {e}")
        return False


@login_required
@permission_required("sales.add_sale", raise_exception=True)
@require_http_methods(["GET", "POST"])
def create_sale(request):
    """Create new sale with tenant support and customer notes"""
    if request.method == 'GET':
        return render_sale_form(request)
    else:
        # Always resolve company from the request tenant (same as GET path)
        # to guarantee consistent tenant context across the full request cycle.
        company = get_current_tenant(request)
        if not company:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': ['No company context found']}, status=400)
            messages.error(request, 'No company context found')
            return redirect('sales:sales_list')
        return process_sale_creation(request, company)


def render_sale_form(request):
    """Render sale creation form"""
    user = request.user
    company = get_current_tenant(request)

    if not company:
        messages.error(request, 'No company context found')
        return redirect('sales:sales_list')

    with tenant_context_safe(company):
        # Get accessible stores using utility function
        accessible_stores = get_user_accessible_stores(user).filter(
            is_active=True,
            company=company
        )

        stores = accessible_stores.order_by('name').distinct()

        if not stores.exists():
            context = {
                'stores': stores,
                'page_title': 'Create New Sale',
                'form': SaleForm(user=user),
                'no_stores_message': True,
                'error_message': (
                    'No stores available. Please contact administrator.'
                )
            }
            return render(request, 'sales/create_sale.html', context)

        # Get default store
        default_store = None
        if hasattr(user, 'default_store') and user.default_store:
            if stores.filter(id=user.default_store.id).exists():
                default_store = user.default_store

        # If no default store from user, use first available store
        if not default_store and stores.exists():
            default_store = stores.first()

        # Prepare store details for the default store
        store_details = {}
        if default_store:
            store_details = {
                'name': default_store.name,
                'phone': default_store.phone or '',
                'email': default_store.email or '',
                'tin': default_store.tin or '',
                'address': default_store.physical_address or '',
                'logo_url': default_store.logo.url if default_store.logo else '',
                'store_type': default_store.get_store_type_display(),
                'code': default_store.code,
                'location': default_store.location,
                'efris_device_number': default_store.efris_device_number or '',
            }

        context = {
            'stores': stores,
            'page_title': 'Create New Sale',
            'form': SaleForm(user=user),
            'company': company,
            'default_store': default_store,
            'store_details': store_details,
        }

        return render(request, 'sales/create_sale.html', context)


def process_sale_creation(request, company):
    """
    Wrapper: runs atomic work, renders response outside transaction.
    Returns JSON for AJAX requests (X-Requested-With: XMLHttpRequest),
    falls back to redirect for normal browser POSTs.
    """
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    try:
        sale = _process_sale_atomic(request, company)

        if is_ajax:
            # Build item list for the success overlay
            items_summary = []
            for item in sale.items.all():
                if item.item_type == 'SERVICE' and item.service:
                    name = item.service.name
                elif item.product:
                    name = item.product.name
                else:
                    name = getattr(item, 'item_name', 'Item')

                items_summary.append({
                    'name': name,
                    'quantity': str(item.quantity),
                    'unit_price': str(item.unit_price),
                    'total': str(item.line_total),
                    'item_type': item.item_type,
                })

            return JsonResponse({
                'success': True,
                'sale': {
                    'id': sale.pk,
                    'document_number': sale.document_number,
                    'document_type': sale.document_type,
                    'document_type_display': sale.get_document_type_display(),
                    'total_amount': str(sale.total_amount),
                    'subtotal': str(sale.subtotal),
                    'tax_amount': str(sale.tax_amount),
                    'discount_amount': str(sale.discount_amount),
                    'currency': sale.currency,
                    'payment_method': sale.payment_method,
                    'payment_method_display': sale.get_payment_method_display(),
                    'is_fiscalized': sale.is_fiscalized,
                    'efris_invoice_number': sale.efris_invoice_number or '',
                    'customer_name': sale.customer.name if sale.customer else 'Walk-in Customer',
                    'store_name': sale.store.name,
                    'created_at': sale.created_at.strftime('%d %b %Y %H:%M'),
                    'item_count': sale.items.count(),
                    'items': items_summary,
                    # URLs the overlay buttons need
                    'detail_url': reverse('sales:sale_detail', kwargs={'pk': sale.pk}),
                    'print_url': reverse('sales:print_receipt', kwargs={'sale_id': sale.pk}),
                },
            })

        # Normal browser POST fallback
        messages.success(
            request,
            f"{sale.get_document_type_display()} #{sale.document_number} created successfully"
        )
        return redirect('sales:sale_detail', pk=sale.pk)

    except ValidationError as e:
        error_messages = e.message_dict if hasattr(e, 'message_dict') else {'error': e.messages}
        errors = []
        for field, errs in error_messages.items():
            for error in errs:
                errors.append(str(error))
                if not is_ajax:
                    messages.error(request, error)

        if is_ajax:
            return JsonResponse({'success': False, 'errors': errors}, status=400)

        return render_sale_form(request)

    except Exception as e:
        logger.error(f"Error creating sale: {e}", exc_info=True)
        error_msg = f"Failed to create sale: {str(e)}"

        if is_ajax:
            return JsonResponse({'success': False, 'errors': [error_msg]}, status=500)

        messages.error(request, error_msg)
        return render_sale_form(request)


@transaction.atomic
def _process_sale_atomic(request, company):
    """All DB writes happen here. Returns sale on success, raises on failure."""
    sale_data = validate_sale_data(request.POST, request.user, company)

    items_data = validate_items_data(
        request.POST.get('items_data', '[]'),
        is_export_sale=sale_data.get('is_export_sale', False)
    )

    if not items_data:
        raise ValidationError({'items': ['At least one item is required']})

    if sale_data.get('document_type') in ['RECEIPT', 'INVOICE']:
        stock_errors = validate_stock_availability(sale_data['store'], items_data)
        if stock_errors:
            raise ValidationError({'stock': stock_errors})

    sale_data['_defer_auto_fiscalize'] = True

    sale = create_sale_record(request, sale_data, company)
    create_sale_items(sale, items_data)
    sale.update_totals()

    if sale.customer and hasattr(sale.customer, 'notes') and sale.customer.notes:
        logger.info(f"Customer notes for sale {sale.id}: {sale.customer.notes}")

    if sale.payment_method != 'CREDIT' and request.POST.get('payment_amount'):
        handle_payment(sale, request.POST)

    if getattr(sale, '_defer_auto_fiscalize', False):
        try:
            store_config = sale.store.effective_efris_config
            if (store_config.get('enabled', False) and
                    store_config.get('is_active', False) and
                    store_config.get('auto_fiscalize_sales', True)):
                # Schedule fiscalization AFTER the atomic transaction commits
                # so the EFRIS HTTP call never holds the DB transaction open,
                # and a network failure cannot roll back a successfully saved sale.
                sale_id_for_closure = sale.id
                user_id_for_closure = getattr(sale.created_by, 'pk', None)
                transaction.on_commit(
                    lambda: sale._auto_fiscalize_sale()
                )
                logger.info(f"Deferred auto-fiscalization scheduled for sale {sale.id}")
        except Exception as e:
            # Log but don't re-raise — fiscalization failure must not
            # roll back a successfully created sale.
            logger.error(f"Deferred auto-fiscalization scheduling failed for sale {sale.id}: {e}")

    if sale.document_type == 'RECEIPT':
        try:
            from .tasks import process_receipt_async
            transaction.on_commit(lambda: process_receipt_async.delay(sale.id))
        except Exception as e:
            logger.warning(f"Background receipt processing failed for sale {sale.id}: {e}")

    return sale




@login_required
@permission_required("sales.add_sale", raise_exception=True)
def create_sale_with_progress(request):
    """
    Create sale with progress tracking - returns immediately with task ID
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    # Generate unique task ID
    task_id = str(uuid.uuid4())

    # Store initial task data in cache or database (simplified version using session)
    request.session[f'sale_task_{task_id}'] = {
        'status': 'processing',
        'message': 'Creating sale...',
        'progress': 10,
        'sale_id': None,
        'created_at': timezone.now().isoformat()
    }
    request.session.modified = True

    # Extract form data
    form_data = {
        'store': request.POST.get('store'),
        'customer': request.POST.get('customer'),
        'document_type': request.POST.get('document_type', 'RECEIPT'),
        'payment_method': request.POST.get('payment_method'),
        'items_data': request.POST.get('items_data'),
        'discount_amount': request.POST.get('discount_amount', '0'),
        'notes': request.POST.get('notes', ''),
        'due_date': request.POST.get('due_date'),
        'payment_amount': request.POST.get('payment_amount'),
        'payment_reference': request.POST.get('payment_reference', ''),
    }

    # Start background task
    from .tasks import create_sale_background
    task_result = create_sale_background.delay(
        form_data=form_data,
        user_id=request.user.id,
        task_id=task_id
    )

    # Update task with celery task ID
    request.session[f'sale_task_{task_id}']['celery_task_id'] = task_result.id
    request.session.modified = True

    return JsonResponse({
        'success': True,
        'task_id': task_id,
        'celery_task_id': task_result.id,
        'message': 'Sale creation started in background',
        'redirect_url': reverse('sales:task_progress', kwargs={'task_id': task_id})
    })


@login_required
def get_task_status(request, task_id):
    """
    Get status of a background task
    """
    task_data = request.session.get(f'sale_task_{task_id}')

    if not task_data:
        return JsonResponse({
            'success': False,
            'error': 'Task not found'
        }, status=404)

    # If task has a sale_id, include redirect URL
    response_data = {
        'success': True,
        'task_id': task_id,
        'status': task_data.get('status', 'unknown'),
        'message': task_data.get('message', ''),
        'progress': task_data.get('progress', 0),
        'sale_id': task_data.get('sale_id')
    }

    if task_data.get('sale_id'):
        response_data['redirect_url'] = reverse('sales:sale_detail', kwargs={'pk': task_data['sale_id']})

    # Clean up completed tasks
    if task_data.get('status') in ['completed', 'failed', 'error']:
        # Keep for 5 minutes before cleanup
        try:
            created_at_str = task_data.get('created_at', '')
            if created_at_str:
                # fromisoformat may return naive or aware datetime depending on
                # the Python version and the stored string. Normalise to aware.
                created_at = datetime.fromisoformat(created_at_str)
                if created_at.tzinfo is None:
                    from django.utils.timezone import make_aware
                    created_at = make_aware(created_at)
                if timezone.now() - created_at > timedelta(minutes=5):
                    del request.session[f'sale_task_{task_id}']
                    request.session.modified = True
        except (ValueError, TypeError):
            pass  # Malformed date — leave it, cleanup will happen on next request

    return JsonResponse(response_data)


@login_required
def task_progress_page(request, task_id):
    """
    HTML page to display task progress
    """
    return render(request, 'sales/task_progress.html', {'task_id': task_id})



def validate_sale_data(post_data, user, company):
    """Enhanced validation with tenant support, credit checking, and export support"""
    required_fields = ['store', 'payment_method']

    for field in required_fields:
        if not post_data.get(field):
            raise ValidationError(f'{field.replace("_", " ").title()} is required.')

    # Validate store
    try:
        store = Store.objects.get(
            id=post_data['store'],
            company=company,
            is_active=True
        )

        # Check user access using utility function
        try:
            validate_store_access(user, store, action='view', raise_exception=True)
        except PermissionDenied:
            raise ValidationError('Access denied to selected store.')

        # Check if store allows sales
        if not store.allows_sales:
            raise ValidationError(f'Store "{store.name}" does not allow sales.')

    except Store.DoesNotExist:
        raise ValidationError('Invalid store selected.')

    # Validate document type
    document_type = post_data.get('document_type', 'RECEIPT').strip()
    valid_types = [choice[0] for choice in Sale.DOCUMENT_TYPE_CHOICES]
    if document_type not in valid_types:
        document_type = 'RECEIPT'

    # ✅ FIXED: Determine if this is an export sale
    # Export sales are indicated by:
    # 1. document_type = 'INVOICE' AND
    # 2. is_export_sale flag OR invoice_industry_code = '102'
    is_export_sale = (
            document_type == 'INVOICE' and
            (post_data.get('is_export_sale') == 'true' or
             post_data.get('is_export_sale') == '1' or
             post_data.get('invoice_industry_code') == '102')
    )

    delivery_terms_code = None
    export_buyer_country = None
    export_buyer_passport = None

    # Validate payment method
    payment_method = post_data.get('payment_method', 'CASH')
    valid_methods = [choice[0] for choice in Sale.PAYMENT_METHODS]
    if payment_method not in valid_methods:
        raise ValidationError('Invalid payment method.')

    # Validate discount
    try:
        discount_amount = Decimal(post_data.get('discount_amount', '0'))
        if discount_amount < 0:
            raise ValidationError('Discount cannot be negative.')
    except (InvalidOperation, ValueError):
        raise ValidationError('Invalid discount amount.')

    # Validate currency
    currency = post_data.get('currency', 'UGX')
    if len(currency) != 3:
        currency = 'UGX'  # Default to UGX if invalid

    # Validate customer and credit for INVOICE with CREDIT payment
    customer = None
    if post_data.get('customer'):
        try:
            customer = Customer.objects.get(
                id=post_data['customer'],
                store=store
            )

            # CRITICAL: Check credit only for INVOICES with CREDIT payment method
            if document_type == 'INVOICE' and payment_method == 'CREDIT':
                # Ensure customer allows credit
                if not customer.allow_credit:
                    raise ValidationError(
                        f'Customer "{customer.name}" is not authorized for credit purchases. '
                        f'Please select a different payment method.'
                    )

                # Check credit status
                can_purchase, reason = customer.can_purchase_on_credit
                if not can_purchase:
                    raise ValidationError(
                        f'Credit purchase not allowed for {customer.name}: {reason}'
                    )

                # Validate will not exceed credit limit (preliminary check)
                if customer.credit_balance >= customer.credit_limit:
                    raise ValidationError(
                        f'Customer "{customer.name}" has reached credit limit. '
                        f'Outstanding: {customer.credit_balance:,.0f}, '
                        f'Limit: {customer.credit_limit:,.0f}'
                    )

            # Get store's EFRIS configuration for validation
            store_config = store.effective_efris_config
            if store_config.get('enabled', False):
                if hasattr(customer, 'validate_for_efris'):
                    is_valid, errors = customer.validate_for_efris()
                    if not is_valid:
                        logger.warning(f"Customer EFRIS validation: {'; '.join(errors)}")

        except Customer.DoesNotExist:
            raise ValidationError('Invalid customer selected.')
    else:
        # INVOICE with CREDIT requires customer
        if document_type == 'INVOICE' and payment_method == 'CREDIT':
            raise ValidationError('Customer is required for credit invoices.')

    # ✅ FIXED: Validate export-specific requirements (for INVOICE with export flag)
    if is_export_sale:
        # MANDATORY: Customer for export invoices
        if not customer:
            raise ValidationError('Customer is required for export invoices.')

        # MANDATORY: Delivery terms (Incoterms)
        delivery_terms_code = post_data.get('delivery_terms_code', '').strip()
        valid_incoterms = [
            'CFR', 'CIF', 'CIP', 'CPT', 'DAP', 'DDP',
            'DPU', 'EXW', 'FAS', 'FCA', 'FOB'
        ]

        if not delivery_terms_code:
            raise ValidationError('Delivery terms (Incoterms) are required for export invoices.')

        if delivery_terms_code not in valid_incoterms:
            raise ValidationError(
                f'Invalid delivery terms: {delivery_terms_code}. '
                f'Must be one of: {", ".join(valid_incoterms)}'
            )

        # OPTIONAL: Export buyer details (recommended for EFRIS compliance)
        export_buyer_country = post_data.get('export_buyer_country', '').strip()
        export_buyer_passport = post_data.get('export_buyer_passport', '').strip()

        # Validate buyer country code if provided (ISO 3166-1 alpha-2)
        if export_buyer_country and len(export_buyer_country) != 2:
            raise ValidationError('Export buyer country must be a 2-letter country code (e.g., KE, TZ, US).')

        # Log warning if recommended fields are missing
        if not export_buyer_country:
            logger.warning(f"Export invoice missing buyer country for customer: {customer.name}")

    # Validate due date based on document type and payment method
    due_date = None
    if document_type == 'INVOICE' and payment_method == 'CREDIT':
        due_date_str = post_data.get('due_date')
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
                if due_date < timezone.now().date():
                    raise ValidationError('Due date cannot be in the past.')
            except (ValueError, TypeError):
                raise ValidationError('Invalid due date format. Use YYYY-MM-DD.')
        else:
            # Use customer's credit days if available, otherwise default to 30
            credit_days = customer.credit_days if customer else 30
            due_date = timezone.now().date() + timedelta(days=credit_days)
    elif document_type == 'INVOICE':
        # ✅ FIXED: Cash/Card invoices and export invoices can have due date for record keeping
        due_date_str = post_data.get('due_date')
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                due_date = None

    # Validate items - preliminary check
    items_data_json = post_data.get('items_data', '[]')
    try:
        items_data = json.loads(items_data_json) if items_data_json else []

        # Check if any products require inventory management
        has_products = False
        for item in items_data:
            item_type = item.get('item_type', 'PRODUCT')
            if item_type == 'PRODUCT':
                has_products = True
                break

        # If sale has products, check if store allows inventory
        if has_products and not store.allows_inventory:
            raise ValidationError(f'Store "{store.name}" does not allow inventory management for products.')

        # ✅ FIXED: For export sales, validate that items have required export fields
        if is_export_sale and has_products:
            for idx, item in enumerate(items_data, 1):
                if item.get('item_type') == 'PRODUCT':
                    product_id = item.get('product_id')
                    if product_id:
                        # Check will happen in validate_items_data, but we can log here
                        logger.info(f"Export sale - will validate product {product_id} has HS code and weights")

    except json.JSONDecodeError:
        # Will be caught in validate_items_data
        pass

    return {
        'store': store,
        'customer': customer,
        'payment_method': payment_method,
        'document_type': document_type,
        'currency': currency,
        'discount_amount': discount_amount,
        'notes': post_data.get('notes', '').strip(),
        'due_date': due_date,
        # ✅ FIXED: Export-specific fields
        'is_export_sale': is_export_sale,
        'delivery_terms_code': delivery_terms_code,
        'export_buyer_country': export_buyer_country,
        'export_buyer_passport': export_buyer_passport,
    }


def validate_items_data(items_json, is_export_sale=False):
    """
    Validate items data from JSON string.
    For export sales, checks weight from the items_json data (frontend state)
    instead of database to allow recently configured products to pass validation.

    ✅ FIXED: Now checks frontend data first, then database
    """
    try:
        items_data = json.loads(items_json) if isinstance(items_json, str) else items_json
    except json.JSONDecodeError:
        raise ValidationError("Invalid items data format")

    if not items_data or not isinstance(items_data, list):
        raise ValidationError("Items data must be a non-empty list")

    validated_items = []

    for idx, item in enumerate(items_data, 1):
        # Basic validation
        item_type = item.get('item_type', 'PRODUCT')

        if item_type not in ['PRODUCT', 'SERVICE']:
            raise ValidationError(f"Item {idx}: Invalid item_type")

        # Get product or service
        if item_type == 'PRODUCT':
            product_id = item.get('product_id')
            if not product_id:
                raise ValidationError(f"Item {idx}: product_id required for PRODUCT type")

            try:
                product = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                raise ValidationError(f"Item {idx}: Product not found")

            # ✅ CRITICAL FIX: For export sales, check weight from frontend data FIRST
            # This allows recently configured products (via modal) to pass validation
            # even if database hasn't been updated yet
            if is_export_sale and item_type == 'PRODUCT':
                # STEP 1: Try to get weight from frontend data (recently configured via modal)
                item_weight = item.get('item_weight') or item.get('totalWeight')

                # STEP 2: If not in frontend data, check database (already saved products)
                if not item_weight:
                    item_weight = getattr(product, 'item_weight', None)

                # STEP 3: Convert to float and validate
                try:
                    weight_value = float(item_weight) if item_weight else 0
                except (ValueError, TypeError):
                    weight_value = 0

                # STEP 4: Validate weight is positive
                if weight_value <= 0:
                    raise ValidationError(
                        f"Item {idx} ({product.name}): Product must have weight > 0 for export. "
                        f"Current weight: {item_weight or 'Not set'}. "
                        f"Please configure weight using 'Configure Now' button."
                    )

                # STEP 5: Check export readiness (from frontend or database)
                is_export_ready = item.get('is_export_ready', False) or getattr(product, 'is_export_ready', False)

                if not is_export_ready:
                    raise ValidationError(
                        f"Item {idx} ({product.name}): Product not configured for export. "
                        f"Required: HS code, customs measure unit, and weight. "
                        f"Use 'Configure Now' button to complete setup."
                    )

                # ✅ Log successful validation for debugging
                logger.info(
                    f"✅ Export product validated: {product.name}, "
                    f"weight={weight_value}kg, is_export_ready={is_export_ready}"
                )

            validated_item = {
                'item_type': 'PRODUCT',
                'product': product,
                'service': None,
                'quantity': int(item.get('quantity', 1)),
                'unit_price': Decimal(str(item.get('unit_price', product.selling_price))),
                'tax_rate': item.get('tax_rate', product.tax_rate),
                'discount': Decimal(str(item.get('discount', 0))),
                'description': item.get('description', product.name),
            }

        else:  # SERVICE
            service_id = item.get('service_id')
            if not service_id:
                raise ValidationError(f"Item {idx}: service_id required for SERVICE type")

            try:
                service = Service.objects.get(id=service_id)
            except Service.DoesNotExist:
                raise ValidationError(f"Item {idx}: Service not found")

            validated_item = {
                'item_type': 'SERVICE',
                'product': None,
                'service': service,
                'quantity': int(item.get('quantity', 1)),
                'unit_price': Decimal(str(item.get('unit_price', service.unit_price))),
                'tax_rate': item.get('tax_rate', service.tax_rate),
                'discount': Decimal(str(item.get('discount', 0))),
                'description': item.get('description', service.name),
            }

        validated_items.append(validated_item)

    return validated_items


def create_sale_record(request, sale_data, company):
    """
    Create sale record with export support.
    Export customer fields are fetched from Customer model.
    """
    document_type = sale_data.get('document_type', 'RECEIPT')

    # Set due date for invoices
    due_date = sale_data.get('due_date')
    if document_type == 'INVOICE' and not due_date:
        from datetime import timedelta
        due_date = (timezone.now() + timedelta(days=30)).date()

    # ✅ CHANGED: Fetch export fields from Customer model
    export_kwargs = {}
    if sale_data.get('is_export_sale'):
        customer = sale_data.get('customer')

        export_kwargs = {
            'is_export_sale': True,
            'invoice_industry_code': '102',
            'delivery_terms_code': sale_data.get('delivery_terms_code', ''),
            'export_delivery_terms': sale_data.get('delivery_terms_code', ''),
        }

        # Fetch from Customer model if customer exists
        if customer:
            export_kwargs['export_buyer_country'] = (
                    getattr(customer, 'country', '') or
                    sale_data.get('buyer_country', '')
            )
            export_kwargs['export_buyer_passport'] = (
                    getattr(customer, 'passport_number', '') or
                    sale_data.get('buyer_passport', '')
            )

        # Currency and exchange rate from sale_data
        export_kwargs['export_currency'] = sale_data.get('export_currency', 'UGX')
        export_kwargs['export_exchange_rate'] = sale_data.get('export_exchange_rate')

    sale = Sale.objects.create(
        store=sale_data['store'],
        created_by=request.user,
        customer=sale_data.get('customer'),
        document_type=document_type,
        payment_method=sale_data.get('payment_method', 'CASH'),
        due_date=due_date,
        subtotal=sale_data.get('subtotal', 0),
        tax_amount=sale_data.get('tax_amount', 0),
        discount_amount=sale_data.get('discount_amount', 0),
        total_amount=sale_data.get('total_amount', 0),
        currency=sale_data.get('currency', 'UGX'),
        notes=sale_data.get('notes', ''),
        transaction_type='SALE',
        **export_kwargs  # ✅ Apply export fields from Customer
    )

    # Stamp the defer flag
    if sale_data.get('_defer_auto_fiscalize'):
        sale._defer_auto_fiscalize = True

    logger.info(
        f"Created {document_type} sale {sale.document_number} "
        f"(export={sale_data.get('is_export_sale', False)})"
    )

    return sale


def create_sale_items(sale, items_data):
    """
    Create SaleItem records for a sale.
    For export sales, ALL export fields must be saved to SaleItem for EFRIS.

    ✅ CORRECTED: Uses your actual field names (export_total_weight, etc.)
    """
    created_items = []

    for idx, item_data in enumerate(items_data, 1):
        try:
            # Determine if this is an export sale item
            is_export_item = (
                    sale.is_export_sale and
                    item_data['item_type'] == 'PRODUCT' and
                    item_data.get('product') is not None
            )

            # ✅ Build export_kwargs using YOUR field names
            export_kwargs = {}

            if is_export_item:
                product = item_data['product']
                quantity = item_data['quantity']

                # ==========================================
                # STEP 1: Get item_weight (per unit) - STRICT VALIDATION
                # ==========================================
                item_weight = None

                # Try frontend data first
                item_weight_from_frontend = (
                        item_data.get('item_weight') or
                        item_data.get('totalWeight')
                )

                if item_weight_from_frontend:
                    try:
                        weight_value = float(item_weight_from_frontend)
                        if weight_value > 0:
                            item_weight = weight_value
                            logger.info(f"✅ Using frontend weight for {product.name}: {item_weight}kg")
                    except (ValueError, TypeError):
                        logger.warning(f"⚠️ Invalid frontend weight for {product.name}: {item_weight_from_frontend}")

                # If no valid frontend weight, check database
                if item_weight is None:
                    db_weight = getattr(product, 'item_weight', None)
                    if db_weight:
                        try:
                            weight_value = float(db_weight)
                            if weight_value > 0:
                                item_weight = weight_value
                                logger.info(f"✅ Using database weight for {product.name}: {item_weight}kg")
                        except (ValueError, TypeError):
                            logger.warning(f"⚠️ Invalid database weight for {product.name}: {db_weight}")

                # ⚠️ CRITICAL: REJECT export items with no valid weight
                # Remove fallback - EFRIS requires real weights
                if item_weight is None or item_weight <= 0:
                    raise ValidationError(
                        f"❌ EXPORT REJECTED: Product '{product.name}' has no weight configured.\n"
                        f"Current weight: {item_weight or 'Not set'}\n"
                        f"Weight is MANDATORY for export invoices per EFRIS requirements.\n"
                        f"Please configure product weight in Product Management before creating export sale."
                    )

                # Calculate total weight (item_weight × quantity)
                export_total_weight = item_weight * quantity

                logger.info(
                    f"💾 Export weight for {product.name}: "
                    f"{item_weight}kg/unit × {quantity} = {export_total_weight}kg total"
                )

                # ==========================================
                # STEP 2: Get pieceQty (from frontend or product)
                # ==========================================
                piece_qty = (
                        item_data.get('pieceQty') or
                        getattr(product, 'piece_qty', None) or
                        quantity  # Fallback: use sale quantity
                )

                try:
                    piece_qty = int(piece_qty)
                except (ValueError, TypeError):
                    piece_qty = int(quantity)

                logger.info(f"Piece quantity for {product.name}: {piece_qty}")

                # ==========================================
                # STEP 3: Get pieceMeasureUnit (customs UoM)
                # ==========================================
                # Your field expects 3-char code from T115 exportRateUnit
                piece_measure_unit = (
                        item_data.get('customs_measure_unit') or
                        getattr(product, 'customs_measure_unit', None) or
                        '101'  # Default: "101" = per stick (your comment says this)
                )

                logger.info(f"Piece measure unit for {product.name}: {piece_measure_unit}")

                # ==========================================
                # STEP 4: Build export_kwargs with YOUR field names
                # ==========================================
                export_kwargs = {
                    'export_total_weight': Decimal(str(export_total_weight)),
                    'export_piece_qty': Decimal(str(piece_qty)),
                    'export_piece_measure_unit': str(piece_measure_unit)[:3],  # Max 3 chars
                }

                # Log what we're about to save
                logger.info(
                    f"💾 Saving export fields for {product.name}:\n"
                    f"   export_total_weight: {export_total_weight}kg\n"
                    f"   export_piece_qty: {piece_qty}\n"
                    f"   export_piece_measure_unit: {piece_measure_unit}"
                )

            # ==========================================
            # STEP 5: Create SaleItem with export fields
            # ==========================================
            sale_item = SaleItem(
                sale=sale,
                item_type=item_data['item_type'],
                product=item_data.get('product'),
                service=item_data.get('service'),
                quantity=item_data['quantity'],
                unit_price=item_data['unit_price'],
                tax_rate=item_data['tax_rate'],
                discount=item_data['discount'],
                description=item_data.get('description', ''),
                **export_kwargs  # ✅ Apply export fields
            )

            # Suppress per-item update_totals — we call it ONCE after the loop.
            # This reduces N aggregate queries (one per item) down to exactly 1.
            sale_item._skip_sale_update = True

            sale_item.save()
            created_items.append(sale_item)

            logger.info(
                f"✅ Created sale item {idx}/{len(items_data)}: "
                f"{sale_item.item_name} x{sale_item.quantity}"
                + (f" [EXPORT with {len(export_kwargs)} fields]" if export_kwargs else "")
            )

        except ValidationError as e:
            error_msg = e.message_dict if hasattr(e, 'message_dict') else {'error': e.messages}
            logger.error(f"❌ Failed to create sale item {idx}: {error_msg}")
            raise ValidationError(f"Failed to create sale item {idx}: {error_msg}")

        except Exception as e:
            logger.error(f"❌ Unexpected error creating sale item {idx}: {str(e)}", exc_info=True)
            raise ValidationError(f"Failed to create sale item {idx}: {str(e)}")

    # ONE update_totals for all N items instead of N separate aggregate queries
    sale.update_totals()
    logger.info(f"✅ Created {len(created_items)} sale items for sale {sale.document_number}")
    return created_items


def create_stock_movements(sale):
    """Create stock movements for products only"""
    try:
        for item in sale.items.select_related('product', 'service'):
            if item.item_type != 'PRODUCT' or not item.product:
                continue

            StockMovement.objects.create(
                product=item.product,
                store=sale.store,
                movement_type='SALE',
                quantity=item.quantity,
                reference=sale.document_number or f"SALE-{sale.id}",
                unit_price=item.unit_price,
                total_value=item.total_price,
                created_by=sale.created_by,
                notes=f"Sale: {sale.document_number}"
            )

    except Exception as e:
        logger.error(f"Error creating stock movements: {e}", exc_info=True)


def handle_payment(sale, post_data):
    """Handle payment creation"""
    try:
        payment_amount = post_data.get('payment_amount', '').strip()
        if not payment_amount:
            return

        amount = Decimal(payment_amount)
        if amount > 0:
            Payment.objects.create(
                sale=sale,
                store=sale.store,
                amount=amount,
                payment_method=sale.payment_method,
                transaction_reference=post_data.get('payment_reference', ''),
                is_confirmed=True,
                confirmed_at=timezone.now(),
                created_by=sale.created_by
            )
            logger.info(f"Created payment {amount} for sale {sale.id}")

    except Exception as e:
        logger.error(f"Error creating payment: {e}", exc_info=True)



def render_sale_form_with_errors(request):
    """Render the sale form with preserved data after errors"""
    user = request.user

    if user.is_superuser:
        stores = Store.objects.filter(is_active=True)
    else:
        # Get user's company
        user_company = getattr(user, 'company', None)

        # If user has a company, get stores from that company
        if user_company:
            stores = Store.objects.filter(
                Q(is_active=True) & (
                    # User is directly assigned as staff
                        Q(staff=user) |
                        # Store belongs to user's company
                        Q(company=user_company)
                )
            ).distinct()
        else:
            # User without company - only show stores where they're staff
            stores = Store.objects.filter(
                staff=user,
                is_active=True
            ).distinct()

    context = {
        'stores': stores,
        'page_title': 'Create New Sale',
        'form_data': request.POST,  # Preserve form data
        'form': SaleForm(user=user, data=request.POST),
    }

    return render(request, 'sales/create_sale.html', context)


@login_required
def search_products(request):
    try:
        from stores.utils import validate_store_access

        query = request.GET.get('q', '').strip()
        store_id = request.GET.get('store_id')

        if len(query) < 2:
            return JsonResponse({'products': []})

        # Validate store access
        store = None
        if store_id:
            try:
                store_id = int(store_id)
                store = Store.objects.get(id=store_id)

                # Validate store access using utility function
                try:
                    validate_store_access(request.user, store, action='view', raise_exception=True)
                except PermissionDenied:
                    return JsonResponse({'error': 'Access denied to store'}, status=403)

            except (ValueError, Store.DoesNotExist):
                return JsonResponse({'error': 'Invalid store'}, status=400)

        # Base product query — use prefetch_related to avoid N+1 stock lookups.
        from django.db.models import Prefetch
        from inventory.models import Stock as StockModel

        products_qs = Product.objects.filter(is_active=True).filter(
            Q(name__icontains=query) |
            Q(sku__icontains=query) |
            Q(barcode__icontains=query)
        ).select_related('category', 'supplier')

        if store:
            products_qs = products_qs.filter(
                store_inventory__store=store,
                store_inventory__quantity__gt=0
            )

        # Prefetch the specific store's stock in one extra query instead of N
        if store:
            products_qs = products_qs.prefetch_related(
                Prefetch(
                    'store_inventory',
                    queryset=StockModel.objects.filter(store=store),
                    to_attr='filtered_stock',
                )
            )

        products = products_qs.distinct()[:20]

        product_data = []
        for product in products:
            stock_info = None
            if store:
                # filtered_stock is pre-fetched — zero extra queries
                stock_list = getattr(product, 'filtered_stock', [])
                if stock_list:
                    stock_info = {
                        'available': float(stock_list[0].quantity),
                        'unit': product.unit_of_measure or 'pcs'
                    }
                else:
                    stock_info = {'available': 0, 'unit': product.unit_of_measure or 'pcs'}

            efris_data = {}
            if hasattr(product, 'get_efris_goods_data'):
                try:
                    efris_data = {
                        'efris_goods_name': product.efris_goods_name if hasattr(product, 'efris_goods_name') else None,
                        'efris_goods_code': product.efris_goods_code if hasattr(product, 'efris_goods_code') else None,
                        'efris_uploaded': getattr(product, 'efris_is_uploaded', False),
                    }
                except Exception as e:
                    logger.warning(f"Error getting EFRIS data for product {product.id}: {e}")

            product_data.append({
                'id': product.id,
                'name': product.name,
                'sku': product.sku or '',
                'barcode': product.barcode or '',
                'price': float(product.selling_price or 0),
                'final_price': float(product.selling_price or 0),  # Updated field name
                'discount_percentage': float(getattr(product, 'discount_percentage', 0)),
                'tax_rate': getattr(product, 'tax_rate', 'A'),
                'unit_of_measure': product.unit_of_measure or 'pcs',
                'stock': stock_info,
                'category': product.category.name if product.category else '',
                'supplier': product.supplier.name if product.supplier else '',
                'efris': efris_data,
            })

        return JsonResponse({'products': product_data})

    except Exception as e:
        logger.error(f"Error in product search: {e}")
        return JsonResponse({'error': 'Search failed'}, status=500)


@login_required
def search_customers(request):
    user = request.user
    try:
        query = request.GET.get('q', '').strip()
        store_id = request.GET.get('store_id')

        if len(query) < 2:
            return JsonResponse({'customers': []})

        # Validate store_id is provided
        if not store_id:
            return JsonResponse({
                'success': False,
                'error': 'Store selection required',
                'customers': []
            }, status=400)

        # Validate store access and existence
        try:
            store = Store.objects.get(id=store_id, is_active=True)
            validate_store_access(request.user, store, action='view', raise_exception=True)
        except Store.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Invalid store',
                'customers': []
            }, status=403)
        except PermissionDenied:
            return JsonResponse({
                'success': False,
                'error': 'Access denied to store',
                'customers': []
            }, status=403)

        # Filter customers based on user access AND store
        if request.user.is_superuser:
            customers = Customer.objects.filter(
                is_active=True,
                store_id=store_id
            )
        else:
            # Fixed: Access company through store relationship (store__company)
            user_company = getattr(user, 'company', None)
            customers = Customer.objects.filter(
                Q(store__company=user_company) | Q(created_by=request.user),
                is_active=True,
                store_id=store_id
            )

        customers = customers.filter(
            Q(name__icontains=query) |
            Q(phone__icontains=query) |
            Q(email__icontains=query) |
            Q(tin__icontains=query) |
            Q(nin__icontains=query) |
            Q(brn__icontains=query)
        ).select_related('store')[:15]

        customer_data = []
        for customer in customers:
            # DO NOT call update_credit_balance() here — it fires a DB write on
            # every keystroke for every result row. Balances are refreshed by
            # the periodic Celery task `refresh_customer_credit_balances`.
            efris_data = {}
            if hasattr(customer, 'get_efris_buyer_details'):
                try:
                    buyer_details = customer.get_efris_buyer_details()
                    efris_data = {
                        'buyer_type': buyer_details.get('buyerType', '1'),
                        'buyer_type_display': 'Business' if buyer_details.get('buyerType') == '0' else 'Individual',
                        'tin': buyer_details.get('buyerTin', ''),
                        'nin_brn': buyer_details.get('buyerNinBrn', ''),
                        'is_efris_ready': all([
                            buyer_details.get('buyerLegalName'),
                            buyer_details.get('buyerMobilePhone')
                        ])
                    }
                except Exception as e:
                    logger.warning(f"Error getting EFRIS buyer details for customer {customer.id}: {e}")

            customer_data.append({
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone or '',
                'email': customer.email or '',
                'address': getattr(customer, 'physical_address', '') or '',
                'tin': getattr(customer, 'tin', '') or '',
                'nin': getattr(customer, 'nin', '') or '',
                'brn': getattr(customer, 'brn', '') or '',
                'customer_type': getattr(customer, 'customer_type', '') or 'INDIVIDUAL',
                'efris': efris_data,
                'store_id': customer.store_id,
                'store_name': customer.store.name if customer.store else None,

                # Credit information
                'credit_info': {
                    'allow_credit': customer.allow_credit,
                    'credit_limit': float(customer.credit_limit),
                    'credit_balance': float(customer.credit_balance),
                    'credit_available': float(customer.credit_available),
                    'credit_status': customer.credit_status,
                    'has_overdue': customer.has_overdue_invoices,
                    'overdue_amount': float(customer.overdue_amount),
                    'can_purchase_credit': customer.can_purchase_on_credit[0],
                    'credit_message': customer.can_purchase_on_credit[1],
                }
            })

        return JsonResponse({
            'success': True,
            'customers': customer_data,
            'count': len(customer_data),
            'store': {
                'id': store.id,
                'name': store.name,
            }
        })

    except Exception as e:
        logger.error(f"Error in customer search: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Search failed',
            'details': str(e) if settings.DEBUG else 'Internal server error',
            'customers': []
        }, status=500)


@login_required
@permission_required('sales.add_sale', raise_exception=True)
@require_http_methods(["GET", "POST"])
def fiscalize_sale(request, sale_id):
    """
    Fiscalize a sale - works for both RECEIPTS and INVOICES using store-specific EFRIS configuration
    """
    sale = get_object_or_404(
        Sale.objects.select_related('store', 'customer', 'created_by'),
        pk=sale_id
    )

    # Check user access using utility function
    try:
        validate_store_access(request.user, sale.store, action='change', raise_exception=True)
    except PermissionDenied as e:
        messages.error(request, str(e))
        return redirect('sales:sales_list')

    # Check if store can fiscalize transactions
    if not sale.store.can_fiscalize:
        config = sale.store.effective_efris_config
        error_parts = []
        if not config.get('enabled', False):
            error_parts.append("EFRIS not enabled")
        if not config.get('is_active', False):
            error_parts.append("EFRIS not active")
        if not config.get('device_number'):
            error_parts.append("No EFRIS device number configured")
        if not config.get('tin'):
            error_parts.append("No TIN configured")
        if not sale.store.is_active:
            error_parts.append("Store is not active")
        if not sale.store.allows_sales:
            error_parts.append("Store doesn't allow sales")

        error_message = f'Store cannot fiscalize transactions: {", ".join(error_parts)}'
        messages.error(request, error_message)
        return redirect('sales:sale_detail', pk=sale_id)

    try:
        # Check if sale can be fiscalized using Sale model's method
        if hasattr(sale, 'can_fiscalize'):
            can_fiscalize, reason = sale.can_fiscalize(request.user)
            if not can_fiscalize:
                messages.error(request, f'Cannot fiscalize sale: {reason}')
                return redirect('sales:sale_detail', pk=sale_id)

        # Check if already fiscalized
        if sale.is_fiscalized:
            messages.warning(request, f'{sale.get_document_type_display()} is already fiscalized.')
            return redirect('sales:sale_detail', pk=sale_id)

        # ALL SALES (receipts and invoices) can be fiscalized directly
        try:
            from .tasks import fiscalize_invoice_async

            # Queue the fiscalization task
            task_result = fiscalize_invoice_async.delay(
            sale.pk, request.user.pk, schema_name=connection.schema_name)

            messages.success(
                request,
                f'Fiscalization queued for {sale.get_document_type_display()} {sale.document_number}. '
                f'Task ID: {task_result.id}. Please check back in a few moments.'
            )

            logger.info(
                f"Fiscalization task queued for sale {sale_id}, "
                f"document_type: {sale.document_type}, task_id: {task_result.id}"
            )

        except ImportError as e:
            logger.error(f"Task import error: {e}")
            messages.error(request, 'Fiscalization service is not available.')
        except Exception as e:
            logger.error(f"Fiscalization queueing error for sale {sale_id}: {e}")
            messages.error(request, f'Failed to queue fiscalization: {str(e)}')

    except Exception as e:
        logger.error(f"Unexpected error during fiscalization of sale {sale_id}: {e}")
        messages.error(request, 'An unexpected error occurred during fiscalization.')

    return redirect('sales:sale_detail', pk=sale_id)

@login_required
@require_POST
def bulk_actions(request):
    """Handle bulk actions on sales - supports all document types"""
    form = BulkActionForm(request.POST)

    if form.is_valid():
        action = form.cleaned_data['action']
        sale_ids = form.cleaned_data['selected_sales']

        # Get sales with proper relationships for EFRIS operations
        sales = Sale.objects.select_related(
            'store__company', 'customer'
        ).filter(id__in=sale_ids)

        if action == 'fiscalize':
            try:
                total_queued = 0
                total_errors = 0
                error_messages = []

                for sale in sales:
                    try:
                        # Validate store EFRIS configuration
                        store_config = sale.store.effective_efris_config
                        if not store_config.get('enabled', False):
                            error_messages.append(f"EFRIS not enabled for sale {sale.document_number}")
                            total_errors += 1
                            continue

                        # Check if sale can be fiscalized
                        if hasattr(sale, 'can_fiscalize'):
                            can_fiscalize, reason = sale.can_fiscalize(request.user)
                            if not can_fiscalize:
                                error_messages.append(f"Sale {sale.document_number}: {reason}")
                                total_errors += 1
                                continue

                        # Skip if already fiscalized
                        if sale.is_fiscalized:
                            continue

                        # Queue fiscalization for ANY sale type (receipt or invoice)
                        from .tasks import fiscalize_invoice_async
                        fiscalize_invoice_async.delay(
                        sale.pk, request.user.pk,
                        schema_name=connection.schema_name)
                        total_queued += 1

                    except Exception as e:
                        logger.error(f"Error processing sale {sale.id} for bulk fiscalization: {e}")
                        error_messages.append(f"Sale {sale.document_number}: {str(e)}")
                        total_errors += 1

                # Prepare result message
                if total_queued > 0:
                    messages.success(request, f'{total_queued} sales queued for fiscalization.')

                if total_errors > 0:
                    error_summary = f'{total_errors} fiscalization errors occurred.'
                    if error_messages:
                        error_summary += f' First few errors: {"; ".join(error_messages[:3])}'
                    messages.error(request, error_summary)

            except ImportError:
                messages.error(request, 'Fiscalization service is not available.')
            except Exception as e:
                logger.error(f"Unexpected error in bulk fiscalization: {e}")
                messages.error(request, 'An error occurred during bulk fiscalization.')

        elif action == 'print_receipts':
            # Generate batch receipt printing
            receipts = []
            for sale in sales:
                receipt, created = Receipt.objects.get_or_create(
                    sale=sale,
                    defaults={
                        'receipt_number': f"RCP-{sale.document_number}",
                        'printed_by': request.user,
                        'receipt_data': {}
                    }
                )
                receipts.append(receipt)

            messages.success(request, f'{len(receipts)} receipts queued for printing.')

        elif action in ['export_csv', 'export_excel']:
            return export_sales(request, sales, action)

    return redirect('sales:sales_list')


def validate_stock_availability(store, items_data):
    """Validate stock for products only"""
    errors = []

    for item_data in items_data:
        if item_data.get('item_type') != 'PRODUCT':
            continue

        product = item_data.get('product')
        if not product:
            continue

        try:
            stock = Stock.objects.filter(
                product=product,
                store=store
            ).first()

            if not stock:
                errors.append(
                    f'No stock record for {product.name} at {store.name}'
                )
                continue

            if stock.quantity < item_data['quantity']:
                errors.append(
                    f'Insufficient stock for {product.name}. '
                    f'Available: {stock.quantity}, Required: {item_data["quantity"]}'
                )

        except Exception as e:
            logger.error(f"Stock validation error: {e}", exc_info=True)
            errors.append(f'Stock check failed for {product.name}')

    return errors

@login_required
@permission_required('sales.view_sale', raise_exception=True)
def sales_efris_status(request):
    user=request.user
    """
    Dashboard view showing EFRIS status for sales and invoices.
    """
    # Get user's accessible stores
    if request.user.is_superuser:

        stores = Store.objects.filter(is_active=True)
    else:
        user_company = getattr(user, 'company', None)
        stores = Store.objects.filter(
            Q(staff=request.user) | Q(company=user_company),
            is_active=True
        ).distinct()

    # Filter by company with EFRIS enabled
    efris_companies = set()
    for store in stores:
        if getattr(store.company, 'efris_enabled', False):
            efris_companies.add(store.company)

    if not efris_companies:
        messages.info(request, 'No companies with EFRIS enabled found.')
        return render(request, 'sales/efris_status.html', {
            'efris_enabled': False
        })

    # Get date range
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if not date_from:
        date_from = timezone.now().date() - timedelta(days=30)
    else:
        date_from = datetime.strptime(date_from, '%Y-%m-%d').date()

    if not date_to:
        date_to = timezone.now().date()
    else:
        date_to = datetime.strptime(date_to, '%Y-%m-%d').date()

    # Get sales in date range from EFRIS-enabled companies
    sales_queryset = Sale.objects.filter(
        store__company__in=efris_companies,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
        transaction_type='SALE'
    )

    # Calculate EFRIS statistics
    total_sales = sales_queryset.count()
    fiscalized_sales = sales_queryset.filter(is_fiscalized=True).count()

    # Recent EFRIS activity (last 24 hours)
    recent_start = timezone.now() - timedelta(hours=24)
    recent_fiscalized = sales_queryset.filter(
        fiscalization_time__gte=recent_start
    ).count()

    # Company-wise statistics
    company_stats = []
    for company in efris_companies:
        company_sales = sales_queryset.filter(store__company=company)
        company_fiscalized = company_sales.filter(is_fiscalized=True).count()

        company_stats.append({
            'company': company,
            'total_sales': company_sales.count(),
            'fiscalized_count': company_fiscalized,
            'fiscalization_rate': (
                    company_fiscalized / company_sales.count() * 100) if company_sales.count() > 0 else 0,
            'efris_config_valid': True,  # Would check actual config validation here
        })

    context = {
        'efris_enabled': True,
        'date_from': date_from,
        'date_to': date_to,
        'total_sales': total_sales,
        'fiscalized_sales': fiscalized_sales,
        'fiscalization_rate': (fiscalized_sales / total_sales * 100) if total_sales > 0 else 0,
        'recent_fiscalized': recent_fiscalized,
        'company_stats': company_stats,
        'efris_companies': list(efris_companies),
    }

    return render(request, 'sales/efris_status.html', context)




@login_required
def pos_interface(request):
    store_id = request.GET.get('store')

    if not store_id or not store_id.isdigit():
        # Get accessible stores for user
        stores = get_user_accessible_stores(request.user).filter(is_active=True)
        return render(request, 'sales/select_store.html', {'stores': stores})

    store = get_object_or_404(Store, id=store_id)

    # Validate store access
    try:
        validate_store_access(request.user, store, action='view', raise_exception=True)
    except PermissionDenied:
        messages.error(request, 'You do not have access to this store')
        # Redirect to store selection with accessible stores
        stores = get_user_accessible_stores(request.user).filter(is_active=True)
        return render(request, 'sales/select_store.html', {'stores': stores})

    if not request.session.session_key:
        request.session.create()

    cart, _ = Cart.objects.get_or_create(
        session_key=request.session.session_key,
        user=request.user,
        store=store,
        status='OPEN',
        defaults={'created_at': timezone.now()}
    )

    context = {
        'store': store,
        'cart': cart,
        'products': Product.objects.filter(store_inventory__store=store),
        'customers': Customer.objects.filter(store_id=request.GET.get('store'))[:100],
        'payment_methods': Sale.PAYMENT_METHODS,
    }

    return render(request, 'sales/pos.html', context)


@login_required
@permission_required('sales.add_cart', raise_exception=True)
@require_POST
def add_to_cart(request):
    try:
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"JSON decode error: {e}, request.body: {request.body}")
                return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
        else:
            # Handle form data (POST parameters)
            data = request.POST

        cart_id = data.get('cart_id')
        product_id = data.get('product_id')
        quantity = data.get('quantity', 1)

        # Validate required fields
        if not cart_id:
            return JsonResponse({'success': False, 'error': 'Cart ID is required'}, status=400)

        if not product_id:
            return JsonResponse({'success': False, 'error': 'Product ID is required'}, status=400)

        try:
            quantity = Decimal(str(quantity))
            if quantity <= 0:
                raise ValueError("Quantity must be positive")
        except (InvalidOperation, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid quantity'}, status=400)

        cart = get_object_or_404(Cart, id=cart_id, user=request.user)
        product = get_object_or_404(Product, id=product_id)

        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            defaults={
                'quantity': quantity,
                'unit_price': product.selling_price,
            }
        )

        if not created:
            cart_item.quantity += quantity
            cart_item.save()

        cart.update_totals()

        return JsonResponse({
            'success': True,
            'item_id': cart_item.id,
            'subtotal': str(cart.subtotal),
            'total_amount': str(cart.total_amount),
            'item_count': cart.items.count()
        })
    except Exception as e:
        logger.error(f"Error in add_to_cart: {e}")
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@permission_required('sales.delete_cart', raise_exception=True)
@require_POST
def remove_from_cart(request, item_id):
    try:
        item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        cart = item.cart
        item.delete()
        cart.update_totals()

        return JsonResponse({
            'success': True,
            'subtotal': str(cart.subtotal),
            'total_amount': str(cart.total_amount),
            'item_count': cart.items.count()
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
def checkout_cart(request):
    try:
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"JSON decode error in checkout: {e}, request.body: {request.body}")
                return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
        else:
            # Handle form data (POST parameters)
            data = request.POST

        cart_id = data.get('cart_id')
        payment_method = data.get('payment_method')
        cash_received = data.get('cash_received', '0')

        # Validate required fields
        if not cart_id:
            return JsonResponse({'success': False, 'error': 'Cart ID is required'}, status=400)

        if not payment_method:
            return JsonResponse({'success': False, 'error': 'Payment method is required'}, status=400)

        cart = get_object_or_404(Cart, id=cart_id, user=request.user)

        if not cart.items.exists():
            return JsonResponse({'success': False, 'error': 'Cart is empty'}, status=400)

        try:
            cash_received = Decimal(str(cash_received))
            if cash_received < 0:
                cash_received = Decimal('0')
        except (InvalidOperation, ValueError):
            cash_received = Decimal('0')

        with transaction.atomic():
            sale = cart.confirm(payment_method, request.user)

            if payment_method == 'CASH' and cash_received > 0:
                Payment.objects.create(
                    sale=sale,
                    amount=cash_received,
                    payment_method=payment_method,
                    is_confirmed=True,
                    confirmed_at=timezone.now()
                )

            # Create new empty cart for session/user/store
            Cart.objects.create(
                session_key=request.session.session_key,
                user=request.user,
                store=cart.store,
                status='OPEN'
            )

            change_due = cash_received - sale.total_amount if cash_received > sale.total_amount else Decimal('0')

            return JsonResponse({
                'success': True,
                'sale_id': sale.pk,
                'invoice_number': sale.invoice_number,
                'total_amount': str(sale.total_amount),
                'change_due': str(change_due.quantize(Decimal('0.01'))),
            })

    except Exception as e:
        logger.error(f"Error in checkout_cart: {e}")
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@permission_required('sales.add_sale', raise_exception=True)
@require_http_methods(["GET", "POST"])
def quick_sale(request):
    if request.method == 'GET':
        # Get stores user has access to
        accessible_stores = get_user_accessible_stores(request.user).filter(
            is_active=True
        ).order_by('name')

        # Get customers from stores user has access to
        store_ids = accessible_stores.values_list('id', flat=True)
        customers = Customer.objects.filter(
            store_id__in=store_ids
        ).distinct().order_by('name')[:100]

        # Add EFRIS status information to context
        context = {
            'stores': accessible_stores,
            'customers': customers,
        }

        # Add EFRIS configuration info for stores
        efris_stores = []
        for store in accessible_stores:
            store_config = store.effective_efris_config
            store_info = {
                'id': store.id,
                'name': store.name,
                'efris_enabled': store_config.get('enabled', False),
                'auto_create_invoices': getattr(store.company, 'auto_create_invoices', False) if store.company else False,
                'auto_fiscalize': store_config.get('auto_fiscalize_sales', False),
            }
            efris_stores.append(store_info)

        context['efris_stores'] = efris_stores

        return render(request, 'sales/quick_sale.html', context)

    # Handle POST request - keeping existing logic
    return JsonResponse({'success': False, 'error': 'POST handler not implemented in this snippet'})




def export_sales(request, sales, format_type):
    """Export sales data"""
    if format_type == 'export_csv':
        response = HttpResponse(content_type='text/csv')
        response[
            'Content-Disposition'] = f'attachment; filename="sales_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Document Number', 'Document Type', 'Transaction ID', 'Date', 'Customer', 'Store',
            'Payment Method', 'Subtotal', 'Tax', 'Discount', 'Total', 'Status'
        ])

        for sale in sales:
            writer.writerow([
                sale.document_number,  # Changed from invoice_number
                sale.get_document_type_display(),  # Added document type
                str(sale.transaction_id),
                sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                sale.customer.name if sale.customer else 'Walk-in',
                sale.store.name,
                sale.get_payment_method_display(),
                sale.subtotal,
                sale.tax_amount,
                sale.discount_amount,
                sale.total_amount,
                'Fiscalized' if sale.is_fiscalized else 'Not Fiscalized'
            ])

        return response

    elif format_type == 'export_excel':
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet('Sales Export')

        # Add headers
        headers = [
            'Document Number', 'Document Type', 'Transaction ID', 'Date', 'Customer', 'Store',
            'Payment Method', 'Subtotal', 'Tax', 'Discount', 'Total', 'Status'
        ]

        for col, header in enumerate(headers):
            worksheet.write(0, col, header)

        # Add data
        for row, sale in enumerate(sales, 1):
            worksheet.write(row, 0, sale.document_number)  # Changed from invoice_number
            worksheet.write(row, 1, sale.get_document_type_display())  # Added
            worksheet.write(row, 2, str(sale.transaction_id))
            worksheet.write(row, 3, sale.created_at.strftime('%Y-%m-%d %H:%M:%S'))
            worksheet.write(row, 4, sale.customer.name if sale.customer else 'Walk-in')
            worksheet.write(row, 5, sale.store.name)
            worksheet.write(row, 6, sale.get_payment_method_display())
            worksheet.write(row, 7, float(sale.subtotal))
            worksheet.write(row, 8, float(sale.tax_amount))
            worksheet.write(row, 9, float(sale.discount_amount))
            worksheet.write(row, 10, float(sale.total_amount))
            worksheet.write(row, 11, 'Fiscalized' if sale.is_fiscalized else 'Not Fiscalized')

        workbook.close()
        output.seek(0)

        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response[
            'Content-Disposition'] = f'attachment; filename="sales_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

        return response


@require_http_methods(["GET"])
def store_sales_api(request):
    logger.info(f"store_sales_api called with parameters: {dict(request.GET.items())}")

    try:
        # Get parameters
        store_id = request.GET.get('store_id')
        logger.debug(f"Received store_id: {store_id}")

        # Validate store_id
        if not store_id:
            logger.warning("store_id parameter is missing")
            return JsonResponse({'error': 'store_id is required'}, status=400)

        # Validate and convert page parameter
        try:
            page = int(request.GET.get('page', 1))
            if page < 1:
                page = 1
        except (ValueError, TypeError):
            logger.warning(f"Invalid page parameter: {request.GET.get('page')}")
            page = 1

        date_range = request.GET.get('date_range', 'week')
        transaction_type = request.GET.get('transaction_type', '')
        payment_method = request.GET.get('payment_method', '')
        document_type = request.GET.get('document_type', '')  # Added document_type filter
        search = request.GET.get('search', '')
        per_page = 25

        logger.debug(
            f"Parsed parameters - page: {page}, date_range: {date_range}, transaction_type: {transaction_type}")

        # Base queryset - filter by store
        try:
            queryset = Sale.objects.filter(store_id=store_id).select_related('customer', 'store', 'created_by')
            logger.debug(f"Base queryset created, initial count: {queryset.count()}")
        except Exception as e:
            logger.error(f"Error creating base queryset: {e}")
            return JsonResponse({'error': 'Database query failed'}, status=500)

        # Apply date range filter
        try:
            now = timezone.now()
            logger.debug(f"Current time: {now}")

            if date_range == 'today':
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                queryset = queryset.filter(created_at__gte=start_date)
                logger.debug(f"Applied 'today' filter from {start_date}")
            elif date_range == 'yesterday':
                yesterday = now - timedelta(days=1)
                start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
                queryset = queryset.filter(created_at__range=(start_date, end_date))
                logger.debug(f"Applied 'yesterday' filter from {start_date} to {end_date}")
            elif date_range == 'week':
                # Current week (Monday to Sunday)
                days_since_monday = now.weekday()
                start_date = (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0,
                                                                               microsecond=0)
                queryset = queryset.filter(created_at__gte=start_date)
                logger.debug(f"Applied 'week' filter from {start_date}")
            elif date_range == 'month':
                start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                queryset = queryset.filter(created_at__gte=start_date)
                logger.debug(f"Applied 'month' filter from {start_date}")
            elif date_range == 'year':
                start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                queryset = queryset.filter(created_at__gte=start_date)
                logger.debug(f"Applied 'year' filter from {start_date}")

            logger.debug(f"Queryset count after date filter: {queryset.count()}")
        except Exception as e:
            logger.error(f"Error applying date filter: {e}")
            return JsonResponse({'error': 'Date filter error'}, status=500)

        # Apply other filters
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)

        if payment_method:
            queryset = queryset.filter(payment_method=payment_method)

        if document_type:  # Added document_type filter
            queryset = queryset.filter(document_type=document_type)

        if search:
            # Updated search to use document_number instead of invoice_number
            queryset = queryset.filter(
                Q(document_number__icontains=search) |
                Q(transaction_id__icontains=search) |
                Q(efris_invoice_number__icontains=search) |  # Added EFRIS invoice number search
                Q(customer__name__icontains=search) |
                Q(customer__phone__icontains=search) |
                Q(customer__email__icontains=search) |
                Q(customer__tin__icontains=search)
            ).distinct()

        # Order by creation date (newest first)
        queryset = queryset.order_by('-created_at')

        # Calculate statistics
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_sales = queryset.filter(created_at__gte=today_start)
        today_stats = today_sales.aggregate(
            count=Count('id'),
            revenue=Sum('total_amount'),
            fiscalized_count=Count('id', filter=Q(is_fiscalized=True)),
            receipts_count=Count('id', filter=Q(document_type='RECEIPT')),
            invoices_count=Count('id', filter=Q(document_type='INVOICE')),
        )

        # Calculate document type statistics
        document_type_stats = queryset.values('document_type').annotate(
            count=Count('id'),
            total=Sum('total_amount')
        )

        overall_stats = queryset.aggregate(
            avg_amount=Avg('total_amount'),
            min_amount=Min('total_amount'),
            max_amount=Max('total_amount')
        )

        stats = {
            'today_count': today_stats['count'] or 0,
            'today_revenue': float(today_stats['revenue'] or 0),
            'today_fiscalized': today_stats['fiscalized_count'] or 0,
            'today_receipts': today_stats['receipts_count'] or 0,
            'today_invoices': today_stats['invoices_count'] or 0,
            'avg_amount': float(overall_stats['avg_amount'] or 0),
            'min_amount': float(overall_stats['min_amount'] or 0),
            'max_amount': float(overall_stats['max_amount'] or 0),
            'fiscalized_count': today_stats['fiscalized_count'] or 0,
            'document_type_stats': {
                doc['document_type']: {
                    'count': doc['count'],
                    'total': float(doc['total'] or 0)
                }
                for doc in document_type_stats
            }
        }

        # Paginate results
        paginator = Paginator(queryset, per_page)
        page_obj = paginator.get_page(page)

        # Serialize sales data
        sales_data = []
        for sale in page_obj:
            customer_data = None
            if sale.customer:
                customer_data = {
                    'id': sale.customer.id,
                    'name': sale.customer.name,
                    'phone': getattr(sale.customer, 'phone', ''),
                    'email': getattr(sale.customer, 'email', ''),
                    'tin': getattr(sale.customer, 'tin', ''),
                }

            # Get payment status and amount paid
            payments = sale.payments.filter(is_confirmed=True).aggregate(
                total_paid=Sum('amount')
            )
            total_paid = payments['total_paid'] or Decimal('0')

            sale_data = {
                'id': sale.id,
                'document_number': sale.document_number or '',  # Changed from invoice_number
                'document_type': sale.document_type,
                'document_type_display': sale.get_document_type_display(),
                'transaction_id': str(sale.transaction_id),
                'created_at': sale.created_at.isoformat() if sale.created_at else '',
                'customer': customer_data,
                'payment_method': sale.payment_method,
                'payment_method_display': sale.get_payment_method_display(),
                'payment_status': sale.payment_status,
                'payment_status_display': sale.get_payment_status_display(),
                'transaction_type': sale.transaction_type,
                'transaction_type_display': sale.get_transaction_type_display(),
                'subtotal': float(sale.subtotal),
                'tax_amount': float(sale.tax_amount),
                'discount_amount': float(sale.discount_amount),
                'total_amount': float(sale.total_amount),
                'currency': sale.currency,
                'status': sale.status,
                'status_display': sale.get_status_display(),
                'is_fiscalized': sale.is_fiscalized,
                'is_refunded': sale.is_refunded,
                'is_voided': sale.is_voided,
                'efris_invoice_number': sale.efris_invoice_number or '',
                'verification_code': sale.verification_code or '',
                'fiscalization_time': sale.fiscalization_time.isoformat() if sale.fiscalization_time else None,
                'total_paid': float(total_paid),
                'amount_outstanding': float(sale.amount_outstanding),
                'item_count': sale.item_count,
                'created_by': {
                    'id': sale.created_by.id,
                    'name': sale.created_by.get_full_name() or sale.created_by.username,
                } if sale.created_by else None,
                'store': {
                    'id': sale.store.id,
                    'name': sale.store.name,
                } if sale.store else None,
                'notes': sale.notes or '',
                'due_date': sale.due_date.isoformat() if sale.due_date else None,
            }
            sales_data.append(sale_data)

        # Pagination info
        pagination = {
            'current_page': page_obj.number,
            'num_pages': paginator.num_pages,
            'has_previous': page_obj.has_previous(),
            'has_next': page_obj.has_next(),
            'previous_page_number': page_obj.previous_page_number() if page_obj.has_previous() else None,
            'next_page_number': page_obj.next_page_number() if page_obj.has_next() else None,
            'total_count': paginator.count,
            'per_page': per_page,
            'start_index': page_obj.start_index(),
            'end_index': page_obj.end_index(),
        }

        # Prepare response with enhanced data
        response_data = {
            'sales': sales_data,
            'stats': stats,
            'pagination': pagination,
            'filters': {
                'store_id': store_id,
                'date_range': date_range,
                'transaction_type': transaction_type,
                'payment_method': payment_method,
                'document_type': document_type,
                'search': search,
                'per_page': per_page,
            },
            'document_types': [
                {'value': choice[0], 'label': choice[1]}
                for choice in Sale.DOCUMENT_TYPE_CHOICES
            ],
            'transaction_types': [
                {'value': choice[0], 'label': choice[1]}
                for choice in Sale.TRANSACTION_TYPES
            ],
            'payment_methods': [
                {'value': choice[0], 'label': choice[1]}
                for choice in Sale.PAYMENT_METHODS
            ],
            'status_choices': [
                {'value': choice[0], 'label': choice[1]}
                for choice in Sale.STATUS_CHOICES
            ],
            'payment_status_choices': [
                {'value': choice[0], 'label': choice[1]}
                for choice in Sale.PAYMENT_STATUS_CHOICES
            ],
        }

        logger.info(f"Successfully returning {len(sales_data)} sales records for store {store_id}")
        return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"Unexpected error in store_sales_api: {e}", exc_info=True)
        return JsonResponse({
            'error': 'An unexpected error occurred while fetching sales data',
            'details': str(e),
            'traceback': str(e.__traceback__) if hasattr(e, '__traceback__') else None
        }, status=500)


@login_required
@permission_required('sales.view_sale', raise_exception=True)
def sales_analytics(request):
    """
    Enhanced sales analytics dashboard supporting both products and services
    """
    try:
        # Date range filtering with validation
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        store_id = request.GET.get('store')

        # Set default date range (last 30 days)
        if not date_from:
            date_from = timezone.now().date() - timedelta(days=30)
        else:
            date_from = datetime.strptime(date_from, '%Y-%m-%d').date()

        if not date_to:
            date_to = timezone.now().date()
        else:
            date_to = datetime.strptime(date_to, '%Y-%m-%d').date()

        # Validate date range
        if date_from > date_to:
            date_from, date_to = date_to, date_from

        # Get user's accessible stores
        accessible_stores = get_user_accessible_stores(request.user).filter(is_active=True)

        # Base queryset filtered by accessible stores
        sales_qs = Sale.objects.filter(
            store__in=accessible_stores,
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
            transaction_type='SALE',
            is_voided=False
        ).select_related('store', 'customer').prefetch_related('items__product', 'items__service', 'payments')

        # Filter by store if specified
        if store_id and store_id != '':
            try:
                store = Store.objects.get(id=store_id)
                # Validate user has access to the selected store
                try:
                    validate_store_access(request.user, store, action='view', raise_exception=True)
                    sales_qs = sales_qs.filter(store_id=store_id)
                except PermissionDenied:
                    messages.error(request, 'Access denied to selected store.')
                    store_id = None  # Reset store_id if access denied
            except Store.DoesNotExist:
                messages.error(request, 'Invalid store selected.')
                store_id = None

        # Get stores for filter dropdown (already filtered by access)
        stores = accessible_stores.order_by('name')

        # Calculate core metrics
        total_sales = sales_qs.count()
        total_revenue = sales_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')
        avg_sale_value = sales_qs.aggregate(Avg('total_amount'))['total_amount__avg'] or Decimal('0')

        # Calculate total customers (distinct customers)
        total_customers = sales_qs.values('customer').distinct().count()
        if total_customers == 0 and total_sales > 0:
            total_customers = total_sales

        # Sales by payment method with enhanced data
        payment_methods_data = sales_qs.values('payment_method').annotate(
            count=Count('id'),
            total=Sum('total_amount')
        ).order_by('-total')

        # Enhanced payment methods with percentages
        payment_methods = []
        for method in payment_methods_data:
            percentage = (method['total'] / total_revenue * 100) if total_revenue > 0 else 0
            payment_methods.append({
                'payment_method': method['payment_method'],
                'payment_method_display': dict(Sale.PAYMENT_METHODS).get(method['payment_method'],
                                                                         method['payment_method']),
                'count': method['count'],
                'total': method['total'],
                'percentage': round(percentage, 1)
            })

        # Daily sales trend with growth calculation
        daily_sales_data = sales_qs.extra(
            select={'day': 'DATE(created_at)'}
        ).values('day').annotate(
            count=Count('id'),
            total=Sum('total_amount')
        ).order_by('day')

        # Process daily sales with growth rates
        daily_sales = []
        previous_total = None
        for day_data in daily_sales_data:
            day_total = day_data['total'] or Decimal('0')
            day_count = day_data['count'] or 0

            # Calculate growth percentage
            growth = None
            if previous_total is not None and previous_total > 0:
                growth_percentage = ((day_total - previous_total) / previous_total) * 100
                growth = f"{growth_percentage:+.1f}%"
            else:
                growth = "+0.0%"

            # Calculate average sale value for the day
            avg_day_value = day_total / day_count if day_count > 0 else Decimal('0')

            daily_sales.append({
                'day': day_data['day'],
                'count': day_count,
                'total': day_total,
                'avg_value': avg_day_value,
                'growth': growth
            })
            previous_total = day_total

        # Top products by revenue - UPDATED to handle both products and services
        from inventory.models import Service

        # Get top products
        top_products_data = SaleItem.objects.filter(
            sale__in=sales_qs,
            item_type='PRODUCT',
            product__isnull=False
        ).select_related('product').values(
            'product__id', 'product__name', 'product__sku'
        ).annotate(
            quantity_sold=Sum('quantity'),
            revenue=Sum('total_price'),
            sale_count=Count('sale', distinct=True)
        ).order_by('-revenue')[:10]

        # Get top services
        top_services_data = SaleItem.objects.filter(
            sale__in=sales_qs,
            item_type='SERVICE',
            service__isnull=False
        ).select_related('service').values(
            'service__id', 'service__name', 'service__code'
        ).annotate(
            quantity_sold=Sum('quantity'),
            revenue=Sum('total_price'),
            sale_count=Count('sale', distinct=True)
        ).order_by('-revenue')[:10]

        # Combine and sort top items (products + services)
        top_items = []

        # Add products
        for product in top_products_data:
            top_items.append({
                'id': product['product__id'],
                'name': product['product__name'],
                'code': product['product__sku'],
                'item_type': 'PRODUCT',
                'quantity_sold': product['quantity_sold'] or 0,
                'revenue': product['revenue'] or Decimal('0'),
                'sale_count': product['sale_count'],
            })

        # Add services
        for service in top_services_data:
            top_items.append({
                'id': service['service__id'],
                'name': service['service__name'],
                'code': service['service__code'],
                'item_type': 'SERVICE',
                'quantity_sold': service['quantity_sold'] or 0,
                'revenue': service['revenue'] or Decimal('0'),
                'sale_count': service['sale_count'],
            })

        # Sort by revenue and take top 10
        top_items.sort(key=lambda x: x['revenue'], reverse=True)
        top_items = top_items[:10]

        # Calculate performance percentage
        max_revenue = top_items[0]['revenue'] if top_items else Decimal('1')
        for item in top_items:
            performance_percentage = (item['revenue'] / max_revenue * 100) if max_revenue > 0 else 0
            item['performance_percentage'] = round(performance_percentage, 1)

        # Hourly sales pattern
        hourly_sales = sales_qs.extra(
            select={'hour': 'EXTRACT(HOUR FROM created_at)'}
        ).values('hour').annotate(
            count=Count('id'),
            total=Sum('total_amount')
        ).order_by('hour')

        # Process hourly data
        hourly_data = []
        for hour in range(24):
            hour_data = next((h for h in hourly_sales if h['hour'] == hour), None)
            if hour_data:
                hourly_data.append({
                    'hour': int(hour),
                    'count': hour_data['count'],
                    'total': hour_data['total'] or Decimal('0')
                })
            else:
                hourly_data.append({
                    'hour': hour,
                    'count': 0,
                    'total': Decimal('0')
                })

        # Sales growth vs previous period
        previous_period_start = date_from - (date_to - date_from) - timedelta(days=1)
        previous_period_end = date_from - timedelta(days=1)

        previous_sales = Sale.objects.filter(
            store__in=accessible_stores,
            created_at__date__gte=previous_period_start,
            created_at__date__lte=previous_period_end,
            transaction_type='SALE',
            is_voided=False
        )

        if store_id and store_id != '':
            previous_sales = previous_sales.filter(store_id=store_id)

        previous_revenue = previous_sales.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')

        if previous_revenue > 0:
            sales_growth = ((total_revenue - previous_revenue) / previous_revenue) * 100
            sales_growth_display = f"{sales_growth:+.1f}%"
        else:
            sales_growth_display = "+0.0%"

        # New customers calculation
        new_customers = sales_qs.filter(
            customer__isnull=False
        ).values('customer').annotate(
            first_sale=Min('created_at')
        ).filter(
            first_sale__date__gte=date_from,
            first_sale__date__lte=date_to
        ).count()

        # Return rate calculation
        refunded_sales = Sale.objects.filter(
            store__in=accessible_stores,
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
            transaction_type='REFUND'
        )

        if store_id and store_id != '':
            refunded_sales = refunded_sales.filter(store_id=store_id)

        refund_amount = refunded_sales.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')

        if total_revenue > 0:
            return_rate = (abs(refund_amount) / total_revenue) * 100
            return_rate_display = f"{return_rate:.1f}%"
        else:
            return_rate_display = "0.0%"

        # Store performance (if multiple stores)
        store_performance = sales_qs.values('store__id', 'store__name').annotate(
            sales_count=Count('id'),
            total_revenue=Sum('total_amount'),
            avg_sale_value=Avg('total_amount')
        ).order_by('-total_revenue')

        # Payment method efficiency
        payment_efficiency = sales_qs.values('payment_method').annotate(
            avg_amount=Avg('total_amount'),
            count=Count('id')
        ).order_by('-avg_amount')

        # Item type breakdown (NEW: Products vs Services analysis)
        item_type_breakdown = SaleItem.objects.filter(
            sale__in=sales_qs
        ).values('item_type').annotate(
            count=Count('id'),
            total_quantity=Sum('quantity'),
            total_revenue=Sum('total_price')
        ).order_by('-total_revenue')

        # Get store statistics with EFRIS status
        store_stats = []
        for store in stores:
            store_config = store.effective_efris_config
            store_sales = sales_qs.filter(store=store)
            store_sales_count = store_sales.count()
            store_revenue = store_sales.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')

            store_stats.append({
                'id': store.id,
                'name': store.name,
                'sales_count': store_sales_count,
                'revenue': store_revenue,
                'efris_enabled': store_config.get('enabled', False),
                'efris_active': store_config.get('is_active', False),
                'allows_sales': store.allows_sales,
                'allows_inventory': store.allows_inventory,
                'is_main_branch': store.is_main_branch,
            })

        context = {
            # Date range
            'date_from': date_from,
            'date_to': date_to,

            # Core metrics
            'total_sales': total_sales,
            'total_revenue': total_revenue,
            'avg_sale_value': avg_sale_value,
            'total_customers': total_customers,

            # Charts data
            'payment_methods': payment_methods,
            'daily_sales': daily_sales,
            'top_items': top_items,
            'hourly_sales': hourly_data,

            # Additional insights
            'sales_growth': sales_growth_display,
            'new_customers': new_customers,
            'return_rate': return_rate_display,

            # Filter options
            'stores': stores,
            'store_stats': store_stats,
            'selected_store': store_id,

            # Additional analytics
            'store_performance': store_performance,
            'payment_efficiency': payment_efficiency,
            'item_type_breakdown': item_type_breakdown,

            # Period information
            'period_days': (date_to - date_from).days + 1,

            # Access information
            'has_multiple_stores': stores.count() > 1,
        }

        # Handle exports
        export_format = request.GET.get('export')
        if export_format in ['csv', 'excel']:
            return export_analytics_data(context, export_format)

        return render(request, 'sales/analytics.html', context)

    except Exception as e:
        logger.error(f"Error in sales analytics: {str(e)}", exc_info=True)
        messages.error(request, f"An error occurred while generating analytics: {str(e)}")

        # Return basic context with default values even on error
        default_date_from = timezone.now().date() - timedelta(days=30)
        default_date_to = timezone.now().date()

        # Get accessible stores for error context
        stores = get_user_accessible_stores(request.user).filter(is_active=True)

        return render(request, 'sales/analytics.html', {
            'date_from': default_date_from,
            'date_to': default_date_to,
            'stores': stores,
            'selected_store': request.GET.get('store'),
            'total_sales': 0,
            'total_revenue': Decimal('0'),
            'avg_sale_value': Decimal('0'),
            'total_customers': 0,
            'payment_methods': [],
            'daily_sales': [],
            'top_items': [],
            'hourly_sales': [],
            'sales_growth': '+0.0%',
            'new_customers': 0,
            'return_rate': '0.0%',
            'store_performance': [],
            'payment_efficiency': [],
            'item_type_breakdown': [],
            'period_days': 30,
            'error': True
        })


@login_required
def analytics_day_details(request):
    """
    AJAX endpoint for day details in analytics - UPDATED to show products and services
    """
    try:
        date_str = request.GET.get('date')
        store_id = request.GET.get('store')

        if not date_str:
            return JsonResponse({'success': False, 'error': 'Date parameter required'})

        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Get sales for the specific day
        sales_qs = Sale.objects.filter(
            created_at__date=target_date,
            transaction_type='SALE',
            is_voided=False
        ).select_related('store', 'customer').prefetch_related('items__product', 'items__service', 'payments')

        if store_id and store_id != '':
            sales_qs = sales_qs.filter(store_id=store_id)

        sales_data = []
        for sale in sales_qs:
            # Count products and services separately
            product_count = sale.items.filter(item_type='PRODUCT').count()
            service_count = sale.items.filter(item_type='SERVICE').count()

            item_summary = []
            if product_count > 0:
                item_summary.append(f"{product_count} product{'s' if product_count > 1 else ''}")
            if service_count > 0:
                item_summary.append(f"{service_count} service{'s' if service_count > 1 else ''}")

            sales_data.append({
                'invoice_number': sale.invoice_number,
                'customer': sale.customer.name if sale.customer else 'Walk-in',
                'total_amount': float(sale.total_amount),
                'payment_method': sale.get_payment_method_display(),
                'created_at': sale.created_at.strftime('%H:%M'),
                'item_count': sale.items.count(),
                'product_count': product_count,
                'service_count': service_count,
                'item_summary': ' + '.join(item_summary),
                'is_fiscalized': sale.is_fiscalized
            })

        # Calculate day statistics
        day_stats = sales_qs.aggregate(
            total_sales=Count('id'),
            total_revenue=Sum('total_amount'),
            avg_sale=Avg('total_amount')
        )

        # Item type statistics for the day
        item_stats = SaleItem.objects.filter(
            sale__in=sales_qs
        ).values('item_type').annotate(
            count=Count('id'),
            revenue=Sum('total_price')
        )

        html_content = render_to_string('sales/includes/day_details.html', {
            'date': target_date,
            'sales': sales_data,
            'stats': day_stats,
            'item_stats': item_stats
        })

        return JsonResponse({
            'success': True,
            'html': html_content
        })

    except Exception as e:
        logger.error(f"Error fetching day details: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})

def export_analytics_data(context, format_type):
    """Export analytics data to CSV or Excel"""
    try:
        if format_type == 'csv':
            response = HttpResponse(content_type='text/csv')
            response[
                'Content-Disposition'] = f'attachment; filename="sales_analytics_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

            writer = csv.writer(response)

            # Write header
            writer.writerow(['Sales Analytics Export', f"Period: {context['date_from']} to {context['date_to']}"])
            writer.writerow([])

            # Key Metrics
            writer.writerow(['Key Metrics'])
            writer.writerow(['Total Sales', context['total_sales']])
            writer.writerow(['Total Revenue', float(context['total_revenue'])])
            writer.writerow(['Average Sale Value', float(context['avg_sale_value'])])
            writer.writerow(['Total Customers', context['total_customers']])
            writer.writerow(['Sales Growth', context['sales_growth']])
            writer.writerow([])

            # Daily Sales
            writer.writerow(['Daily Sales Trend'])
            writer.writerow(['Date', 'Sales Count', 'Total Revenue', 'Average Value', 'Growth'])
            for day in context['daily_sales']:
                writer.writerow([
                    day['day'],
                    day['count'],
                    float(day['total']),
                    float(day['avg_value']),
                    day['growth']
                ])
            writer.writerow([])

            # Top Products
            writer.writerow(['Top Products'])
            writer.writerow(['Product', 'Quantity Sold', 'Revenue', 'Performance %'])
            for product in context['top_products']:
                writer.writerow([
                    product['product__name'],
                    product['quantity_sold'],
                    float(product['revenue']),
                    product['performance_percentage']
                ])

            return response

        elif format_type == 'excel':
            output = BytesIO()
            workbook = xlsxwriter.Workbook(output)
            worksheet = workbook.add_worksheet('Sales Analytics')

            # Add formats
            header_format = workbook.add_format({'bold': True, 'bg_color': '#366092', 'color': 'white'})
            metric_format = workbook.add_format({'bold': True, 'num_format': '#,##0.00'})

            # Key Metrics
            worksheet.write(0, 0, 'Sales Analytics Dashboard', header_format)
            worksheet.write(1, 0, f"Period: {context['date_from']} to {context['date_to']}")

            row = 3
            worksheet.write(row, 0, 'Key Metrics', header_format)
            metrics = [
                ('Total Sales', context['total_sales']),
                ('Total Revenue', float(context['total_revenue'])),
                ('Average Sale Value', float(context['avg_sale_value'])),
                ('Total Customers', context['total_customers']),
                ('Sales Growth', context['sales_growth'])
            ]

            for metric, value in metrics:
                row += 1
                worksheet.write(row, 0, metric)
                if isinstance(value, (int, float)):
                    worksheet.write(row, 1, value, metric_format)
                else:
                    worksheet.write(row, 1, value)

            # Daily Sales Trend
            row += 2
            worksheet.write(row, 0, 'Daily Sales Trend', header_format)
            row += 1
            headers = ['Date', 'Sales Count', 'Total Revenue', 'Average Value', 'Growth']
            for col, header in enumerate(headers):
                worksheet.write(row, col, header, header_format)

            for day_data in context['daily_sales']:
                row += 1
                worksheet.write(row, 0, day_data['day'].strftime('%Y-%m-%d'))
                worksheet.write(row, 1, day_data['count'])
                worksheet.write(row, 2, float(day_data['total']), metric_format)
                worksheet.write(row, 3, float(day_data['avg_value']), metric_format)
                worksheet.write(row, 4, day_data['growth'])

            workbook.close()
            output.seek(0)

            response = HttpResponse(
                output.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response[
                'Content-Disposition'] = f'attachment; filename="sales_analytics_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

            return response

    except Exception as e:
        logger.error(f"Error exporting analytics data: {str(e)}")
        return HttpResponseServerError("Error generating export")

@login_required
def analytics_day_details(request):
    """AJAX endpoint for day details in analytics"""
    try:
        date_str = request.GET.get('date')
        store_id = request.GET.get('store')

        if not date_str:
            return JsonResponse({'success': False, 'error': 'Date parameter required'})

        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Get sales for the specific day
        sales_qs = Sale.objects.filter(
            created_at__date=target_date,
            transaction_type='SALE',
            is_voided=False
        ).select_related('store', 'customer').prefetch_related('items__product', 'payments')

        if store_id and store_id != '':
            sales_qs = sales_qs.filter(store_id=store_id)

        sales_data = []
        for sale in sales_qs:
            sales_data.append({
                'invoice_number': sale.invoice_number,
                'customer': sale.customer.name if sale.customer else 'Walk-in',
                'total_amount': float(sale.total_amount),
                'payment_method': sale.get_payment_method_display(),
                'created_at': sale.created_at.strftime('%H:%M'),
                'item_count': sale.items.count(),
                'is_fiscalized': sale.is_fiscalized
            })

        # Calculate day statistics
        day_stats = sales_qs.aggregate(
            total_sales=Count('id'),
            total_revenue=Sum('total_amount'),
            avg_sale=Avg('total_amount')
        )

        html_content = render_to_string('sales/includes/day_details.html', {
            'date': target_date,
            'sales': sales_data,
            'stats': day_stats
        })

        return JsonResponse({
            'success': True,
            'html': html_content
        })

    except Exception as e:
        logger.error(f"Error fetching day details: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@permission_required('sales.change_sale', raise_exception=True)
@require_http_methods(["GET", "POST"])
def void_sale(request, sale_id):
    """Enhanced void sale functionality with support for both Products and Services"""
    sale = get_object_or_404(
        Sale.objects.select_related('store', 'customer', 'created_by')
        .prefetch_related('items__product', 'items__service', 'payments'),
        pk=sale_id
    )

    # Check user access to this sale and store
    try:
        validate_store_access(request.user, sale.store, action='change', raise_exception=True)
    except PermissionDenied as e:
        messages.error(request, str(e))
        return redirect('sales:sales_list')

    # Check if sale can be voided
    if sale.is_voided:
        messages.warning(request, 'This sale has already been voided.')
        return redirect('sales:sale_detail', pk=sale_id)

    if sale.transaction_type != 'SALE':
        messages.error(request, 'Only regular sales can be voided.')
        return redirect('sales:sale_detail', pk=sale_id)

    # Check if sale has been refunded
    has_refunds = Sale.objects.filter(
        related_sale=sale,
        transaction_type='REFUND'
    ).exists()

    if has_refunds:
        messages.error(request, 'Sales with existing refunds cannot be voided.')
        return redirect('sales:sale_detail', pk=sale_id)

    # Check if sale is too old (configurable business rule)
    max_void_days = getattr(settings, 'MAX_SALE_VOID_DAYS', 7)
    if (timezone.now().date() - sale.created_at.date()).days > max_void_days:
        messages.error(request, f'Sales older than {max_void_days} days cannot be voided.')
        return redirect('sales:sale_detail', pk=sale_id)

    # GET request - show void confirmation form
    if request.method == 'GET':
        # Calculate impact of voiding
        total_payments = sale.payments.filter(is_confirmed=True).aggregate(
            Sum('amount')
        )['amount__sum'] or Decimal('0')

        # Count products and services separately
        product_count = sale.items.filter(item_type='PRODUCT', product__isnull=False).count()
        service_count = sale.items.filter(item_type='SERVICE', service__isnull=False).count()

        context = {
            'sale': sale,
            'total_payments': total_payments,
            'items_count': sale.items.count(),
            'product_count': product_count,
            'service_count': service_count,
            'void_reasons': [
                ('CUSTOMER_REQUEST', 'Customer Request'),
                ('PRICING_ERROR', 'Pricing Error'),
                ('DUPLICATE_TRANSACTION', 'Duplicate Transaction'),
                ('SYSTEM_ERROR', 'System Error'),
                ('FRAUD_PREVENTION', 'Fraud Prevention'),
                ('INVENTORY_ISSUE', 'Inventory Issue'),
                ('OTHER', 'Other (specify in notes)')
            ]
        }

        return render(request, 'sales/void_sale.html', context)

    # POST request - process void
    try:
        with transaction.atomic():
            void_reason = request.POST.get('void_reason', '').strip()
            void_notes = request.POST.get('void_notes', '').strip()

            if not void_reason:
                messages.error(request, 'Void reason is required.')
                return redirect('sales:void_sale', sale_id=sale_id)

            if void_reason == 'OTHER' and not void_notes:
                messages.error(request, 'Please provide detailed notes when selecting "Other" reason.')
                return redirect('sales:void_sale', sale_id=sale_id)

            # Store original values for logging
            original_total = sale.total_amount
            original_document = sale.document_number

            product_items_restored = 0
            service_items_voided = 0

            # Restore stock for products and log services separately
            for item in sale.items.all():
                is_product = item.item_type == 'PRODUCT' and item.product is not None
                is_service = item.item_type == 'SERVICE' and item.service is not None

                if is_product:
                    # Handle product - restore stock
                    try:
                        stock = Stock.objects.select_for_update().get(
                            product=item.product,
                            store=sale.store
                        )
                        stock.quantity += item.quantity  # Add back to inventory
                        stock.save()

                        # Create stock movement record
                        StockMovement.objects.create(
                            product=item.product,
                            store=sale.store,
                            movement_type='VOID',
                            quantity=item.quantity,
                            reference=f"VOID-{sale.document_number or sale.id}",
                            unit_price=item.unit_price,
                            total_value=item.line_total,
                            created_by=request.user,
                            notes=f'Void sale: {original_document}, Reason: {void_reason}'
                        )

                        product_items_restored += 1

                    except Stock.DoesNotExist:
                        logger.warning(
                            f"No stock record found for {item.product.name} "
                            f"at {sale.store.name}. Creating new record."
                        )
                        Stock.objects.create(
                            product=item.product,
                            store=sale.store,
                            quantity=item.quantity,
                            last_updated=timezone.now()
                        )
                        product_items_restored += 1

                elif is_service:
                    # Handle service - just log, no stock to restore
                    logger.info(
                        f"Service voided: {item.service.name}, "
                        f"Quantity: {item.quantity}, Amount: {item.line_total}, "
                        f"Sale: {original_document}, Reason: {void_reason}"
                    )
                    service_items_voided += 1

            # Mark payments as voided
            voided_payments_count = sale.payments.filter(is_confirmed=True).update(
                is_voided=True,
                voided_at=timezone.now(),
                voided_by=request.user,
                void_reason=void_reason
            )

            # Mark sale as voided
            sale.is_voided = True
            sale.void_reason = void_reason
            sale.void_notes = void_notes
            sale.voided_at = timezone.now()
            sale.voided_by = request.user
            sale.status = 'VOIDED'
            sale.save()

            # Create comprehensive audit log entry
            logger.info(
                f"Sale voided: ID={sale.id}, Document={original_document}, "
                f"Amount={original_total}, Reason={void_reason}, "
                f"User={request.user.id}, "
                f"Products_Restored={product_items_restored}, "
                f"Services_Voided={service_items_voided}, "
                f"Payments={voided_payments_count}"
            )

            # Build success message based on what was voided
            success_parts = [f'Sale #{original_document} has been voided successfully.']

            if product_items_restored > 0:
                success_parts.append(f'{product_items_restored} product(s) stock restored.')

            if service_items_voided > 0:
                success_parts.append(f'{service_items_voided} service(s) voided.')

            success_parts.append('Payments have been marked as voided.')

            messages.success(request, ' '.join(success_parts))

            return redirect('sales:sale_detail', pk=sale.pk)

    except Exception as e:
        logger.error(f"Error voiding sale {sale_id}: {e}", exc_info=True)
        messages.error(request, 'An error occurred while voiding the sale. Please try again.')
        return redirect('sales:void_sale', sale_id=sale_id)


@login_required
@permission_required("sales.add_sale", raise_exception=True)
@require_http_methods(["GET", "POST"])
def process_refund(request, sale_id):
    """Enhanced refund processing with support for both Products and Services"""
    sale = get_object_or_404(
        Sale.objects.select_related('store', 'customer', 'created_by')
        .prefetch_related('items__product', 'items__service', 'payments'),
        pk=sale_id
    )

    # Check user access to this sale and store
    try:
        validate_store_access(request.user, sale.store, action='change', raise_exception=True)
    except PermissionDenied as e:
        messages.error(request, str(e))
        return redirect('sales:sales_list')

    # Check if sale can be refunded
    if sale.transaction_type != 'SALE':
        messages.error(request, 'Only regular sales can be refunded.')
        return redirect('sales:sale_detail', pk=sale_id)

    if sale.is_refunded:
        messages.warning(request, 'This sale has already been fully refunded.')
        return redirect('sales:sale_detail', pk=sale_id)

    if sale.is_voided:
        messages.error(request, 'Voided sales cannot be refunded.')
        return redirect('sales:sale_detail', pk=sale_id)

    # GET request - show refund form
    if request.method == 'GET':
        # Get existing refunds for this sale
        existing_refunds = Sale.objects.filter(
            related_sale=sale,
            transaction_type='REFUND'
        ).prefetch_related('items')

        # Calculate refunded amounts per item
        refunded_items = {}
        total_refunded = Decimal('0')

        for refund in existing_refunds:
            total_refunded += abs(refund.total_amount)
            for refund_item in refund.items.all():
                # Handle both products and services
                if refund_item.item_type == 'PRODUCT' and refund_item.product:
                    item_key = f"product_{refund_item.product.id}"
                elif refund_item.item_type == 'SERVICE' and refund_item.service:
                    item_key = f"service_{refund_item.service.id}"
                else:
                    continue

                if item_key not in refunded_items:
                    refunded_items[item_key] = Decimal('0')
                refunded_items[item_key] += abs(refund_item.quantity)

        # Prepare items data for template
        items_data = []
        for item in sale.items.all():
            # Determine if this is a product or service
            is_product = item.item_type == 'PRODUCT' and item.product is not None
            is_service = item.item_type == 'SERVICE' and item.service is not None

            if is_product:
                item_type = 'product'
                item_obj = item.product
                item_key = f"product_{item.product.id}"
            elif is_service:
                item_type = 'service'
                item_obj = item.service
                item_key = f"service_{item.service.id}"
            else:
                continue  # Skip invalid items

            refunded_qty = refunded_items.get(item_key, Decimal('0'))
            available_qty = item.quantity - refunded_qty

            if available_qty > 0:
                items_data.append({
                    'id': item.id,
                    'item_type': item_type,
                    'item': item_obj,
                    'product': item.product if is_product else None,
                    'service': item.service if is_service else None,
                    'original_quantity': item.quantity,
                    'refunded_quantity': refunded_qty,
                    'available_quantity': available_qty,
                    'unit_price': item.unit_price,
                    'line_total': item.line_total,
                    'available_refund_amount': available_qty * item.unit_price,
                    'has_stock': is_product,  # Flag to indicate if stock management needed
                })

        context = {
            'sale': sale,
            'items_data': items_data,
            'existing_refunds': existing_refunds,
            'total_refunded': total_refunded,
            'remaining_amount': sale.total_amount - total_refunded,
            'can_refund': len(items_data) > 0,
            'refund_methods': Sale.PAYMENT_METHODS,
        }

        return render(request, 'sales/process_refund.html', context)

    # POST request - process refund
    try:
        with transaction.atomic():
            refund_reason = request.POST.get('refund_reason', '').strip()
            refund_notes = request.POST.get('refund_notes', '').strip()
            refund_method = request.POST.get('refund_method', 'CASH')

            if not refund_reason:
                messages.error(request, 'Please select a refund reason.')
                return redirect('sales:process_refund', sale_id=sale_id)

            if refund_reason == 'OTHER' and not refund_notes:
                messages.error(request, 'Please provide detailed notes when selecting "Other" reason.')
                return redirect('sales:process_refund', sale_id=sale_id)

            # Collect refund items from POST data
            refund_items_data = []
            for key, value in request.POST.items():
                if key.startswith('refund_qty_'):
                    item_id = key.replace('refund_qty_', '')
                    try:
                        qty = Decimal(str(value))
                        if qty > 0:
                            refund_items_data.append({
                                'item_id': int(item_id),
                                'quantity': qty
                            })
                    except (ValueError, InvalidOperation):
                        continue

            if not refund_items_data:
                messages.error(request, 'Please select at least one item to refund.')
                return redirect('sales:process_refund', sale_id=sale_id)

            # ✅ FIX: Create refund sale record with correct payment_status
            refund_sale = Sale.objects.create(
                store=sale.store,
                customer=sale.customer,
                transaction_type='REFUND',
                related_sale=sale,
                payment_method=refund_method,
                payment_status='PAID',  # ✅ Changed from 'COMPLETED' to 'PAID'
                status='COMPLETED',
                document_type=sale.document_type,
                created_by=request.user,
                notes=f"Refund for sale #{sale.document_number}. Reason: {refund_reason}. {refund_notes}"
            )

            refund_total = Decimal('0')
            product_items_restored = 0
            service_items_refunded = 0

            # Process each refunded item
            for refund_data in refund_items_data:
                original_item = sale.items.get(id=refund_data['item_id'])
                qty = refund_data['quantity']

                # Validate quantity
                if qty > original_item.quantity:
                    raise ValidationError(
                        f"Refund quantity ({qty}) exceeds original quantity ({original_item.quantity}) "
                        f"for {original_item.item_name}"
                    )

                # Determine if this is a product or service
                is_product = original_item.item_type == 'PRODUCT' and original_item.product is not None
                is_service = original_item.item_type == 'SERVICE' and original_item.service is not None

                # Create refund item
                refund_item = SaleItem.objects.create(
                    sale=refund_sale,
                    item_type=original_item.item_type,
                    product=original_item.product if is_product else None,
                    service=original_item.service if is_service else None,
                    quantity=-qty,  # Negative for refund
                    unit_price=original_item.unit_price,
                    discount=original_item.discount,
                    tax_rate=original_item.tax_rate
                )

                item_total = abs(refund_item.line_total)
                refund_total += item_total

                # Only handle stock for products, not services
                if is_product:
                    try:
                        from inventory.models import Stock, StockMovement

                        stock = Stock.objects.select_for_update().get(
                            product=original_item.product,
                            store=sale.store
                        )
                        stock.quantity += qty  # Add back to inventory
                        stock.save()

                        # Create stock movement record
                        StockMovement.objects.create(
                            product=original_item.product,
                            store=sale.store,
                            movement_type='REFUND',
                            quantity=qty,
                            reference=f"REFUND-{refund_sale.document_number or refund_sale.id}",
                            unit_price=original_item.unit_price,
                            total_value=item_total,
                            created_by=request.user,
                            notes=f'Refund from sale: {sale.document_number}, Reason: {refund_reason}'
                        )

                        product_items_restored += 1

                    except Stock.DoesNotExist:
                        logger.warning(
                            f"No stock record found for {original_item.product.name} "
                            f"at {sale.store.name}. Creating new record."
                        )
                        Stock.objects.create(
                            product=original_item.product,
                            store=sale.store,
                            quantity=qty,
                            last_updated=timezone.now()
                        )
                        product_items_restored += 1

                elif is_service:
                    # For services, just log the refund without stock movement
                    logger.info(
                        f"Service refunded: {original_item.service.name}, "
                        f"Quantity: {qty}, Amount: {item_total}, "
                        f"Sale: {sale.document_number}, Reason: {refund_reason}"
                    )
                    service_items_refunded += 1

            # Update refund sale totals
            refund_sale.subtotal = -refund_total
            refund_sale.total_amount = -refund_total
            refund_sale.save()

            # Create refund payment record
            from sales.models import Payment
            Payment.objects.create(
                sale=refund_sale,
                store=sale.store,
                amount=-refund_total,
                payment_method=refund_method,
                is_confirmed=True,
                confirmed_at=timezone.now(),
                created_by=request.user,
                notes=f'Refund payment for sale #{sale.document_number}'
            )

            # Check if sale is fully refunded
            total_refunded = Sale.objects.filter(
                related_sale=sale,
                transaction_type='REFUND'
            ).aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')

            if abs(total_refunded) >= sale.total_amount:
                sale.is_refunded = True
                sale.status = 'REFUNDED'
                sale.save()

            # Create comprehensive audit log entry
            logger.info(
                f"Refund processed: Sale={sale.id}, Refund={refund_sale.id}, "
                f"Amount={refund_total}, Reason={refund_reason}, User={request.user.id}, "
                f"Products_Restored={product_items_restored}, "
                f"Services_Refunded={service_items_refunded}"
            )

            # Build success message based on what was refunded
            success_parts = [f'Refund of {refund_total:,.2f} {sale.currency} processed successfully.']

            if product_items_restored > 0:
                success_parts.append(f'{product_items_restored} product(s) stock restored.')

            if service_items_refunded > 0:
                success_parts.append(f'{service_items_refunded} service(s) refunded.')

            success_parts.append(f'Refund reference: #{refund_sale.document_number}')

            messages.success(request, ' '.join(success_parts))

            return redirect('sales:sale_detail', pk=sale.pk)

    except ValidationError as e:
        logger.error(f"Validation error processing refund for sale {sale_id}: {e}")
        messages.error(request, str(e))
        return redirect('sales:process_refund', sale_id=sale_id)
    except Exception as e:
        logger.error(f"Error processing refund for sale {sale_id}: {e}", exc_info=True)
        messages.error(request, 'An error occurred while processing the refund. Please try again.')
        return redirect('sales:process_refund', sale_id=sale_id)


import qrcode
import io
import base64
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse


@login_required
@permission_required('sales.view_sale', raise_exception=True)
def print_receipt(request, sale_id):
    """Generate and print receipt - supports both products and services"""
    sale = get_object_or_404(
        Sale.objects.select_related('store', 'customer', 'created_by', 'receipt_detail')
        .prefetch_related('items__product', 'items__service', 'payments'),
        id=sale_id
    )

    # Get receipt if exists
    receipt = getattr(sale, 'receipt_detail', None)

    # Build items list that handles both products and services
    items_list = []
    for item in sale.items.all():
        # Determine item name based on type
        if item.item_type == 'SERVICE' and item.service:
            item_name = item.service.name
            item_code = item.service.code or ''
        elif item.product:
            item_name = item.product.name
            item_code = item.product.sku or ''
        else:
            # Fallback to the item_name property if available
            item_name = getattr(item, 'item_name', 'Unknown Item')
            item_code = getattr(item, 'item_code', '')

        items_list.append({
            'name': item_name,
            'code': item_code,
            'item_type': item.item_type,
            'quantity': str(item.quantity),
            'unit_price': str(item.unit_price),
            'discount': str(item.discount_amount or 0),
            'tax': str(item.tax_amount or 0),
            'total': str(item.line_total),
        })

    # --- Generate QR Code with EFRIS verification URL ---
    qr_data = None
    qr_image_src = None

    # Check if we have EFRIS information for QR code
    if sale.is_fiscalized and sale.efris_invoice_number and hasattr(sale, 'verification_code'):
        # Try to get the verification URL using your store's environment
        try:
            # Get store configuration
            store_config = sale.store.effective_efris_config if hasattr(sale.store, 'effective_efris_config') else {}
            is_production = store_config.get('is_production', False)

            if is_production:
                base_url = "https://efris.ura.go.ug/"
                # Build the verification URL using your pattern
                qr_data = f"{base_url}/site_mobile/#/invoiceValidation?invoiceNo={sale.efris_invoice_number}&antiFakeCode={sale.verification_code}"
            else:
                base_url = "https://efristest.ura.go.ug"
                # Build the verification URL using your pattern
                qr_data = f"{base_url}/site_new/#/invoiceValidation?invoiceNo={sale.efris_invoice_number}&antiFakeCode={sale.verification_code}"

        except Exception as e:
            # Fallback to basic data if URL generation fails
            qr_data = f"Receipt: {sale.document_number}\n"
            qr_data += f"Date: {sale.created_at.strftime('%Y-%m-%d')}\n"
            qr_data += f"Amount: {sale.total_amount} {sale.currency}\n"
            if sale.efris_invoice_number:
                qr_data += f"EFRIS: {sale.efris_invoice_number}"

    # If no EFRIS data, create basic receipt QR code
    if not qr_data:
        qr_data = f"Receipt: {sale.document_number}\n"
        qr_data += f"Store: {sale.store.name}\n"
        qr_data += f"Date: {sale.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        qr_data += f"Amount: {sale.total_amount} {sale.currency}\n"
        qr_data += f"TID: {sale.transaction_id}"

    # Generate QR code image
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,  # Increased for better visibility on A4
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)

        # Create PIL image with optimized settings for printing
        qr_img = qr.make_image(fill_color="black", back_color="white")

        # Save to bytes
        buffer = io.BytesIO()
        qr_img.save(buffer, format='PNG', optimize=True)
        buffer.seek(0)

        # Convert to base64 for embedding in HTML
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()
        qr_image_src = f"data:image/png;base64,{qr_base64}"

    except Exception as e:
        # Log error but don't crash
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"QR code generation failed: {str(e)}")
        qr_image_src = None
    # --- End QR Code Generation ---

    # Get or create receipt
    if not receipt:
        # Build receipt data structure
        receipt_data = {
            'sale_data': {
                'document_number': sale.document_number,
                'document_type': sale.document_type,
                'document_type_display': sale.get_document_type_display(),
                'transaction_id': str(sale.transaction_id),
                'created_at': sale.created_at.isoformat(),
                'subtotal': str(sale.subtotal),
                'tax_amount': str(sale.tax_amount),
                'discount_amount': str(sale.discount_amount),
                'total_amount': str(sale.total_amount),
                'payment_method': sale.get_payment_method_display(),
                'currency': sale.currency,
                'is_fiscalized': sale.is_fiscalized,
                'efris_invoice_number': sale.efris_invoice_number or '',
                'verification_code': getattr(sale, 'verification_code', '') or '',
                'qr_data': qr_data,  # Store the QR code data for debugging
            },
            'items': items_list,
            'customer': {
                'name': sale.customer.name if sale.customer else 'Walk-in Customer',
                'phone': sale.customer.phone if sale.customer else '',
                'email': getattr(sale.customer, 'email', '') if sale.customer else '',
                'tin': getattr(sale.customer, 'tin', '') if sale.customer else '',
            },
            'store': {
                'name': sale.store.name,
                'address': getattr(sale.store, 'address', ''),
                'phone': getattr(sale.store, 'phone', ''),
                'tin': getattr(sale.store, 'tin', ''),
            }
        }

        # Create receipt record
        from .models import Receipt
        receipt = Receipt.objects.create(
            sale=sale,
            receipt_number=f"RCP-{sale.document_number}",
            printed_by=request.user,
            receipt_data=receipt_data
        )
    else:
        # Update existing receipt
        receipt.print_count += 1
        receipt.is_duplicate = True
        receipt.last_printed_by = request.user
        receipt.save()

    # Check EFRIS and VAT status
    efris_enabled = False
    vat_enabled = False

    if hasattr(request, 'tenant'):
        efris_enabled = getattr(request.tenant, 'efris_enabled', False)
        vat_enabled = getattr(request.tenant, 'is_vat_enabled', False)
    elif hasattr(request, 'user') and request.user.is_authenticated:
        if hasattr(request.user, 'company'):
            efris_enabled = getattr(request.user.company, 'efris_enabled', False)
            vat_enabled = getattr(request.user.company, 'is_vat_enabled', False)
        elif hasattr(request.user, 'stores') and request.user.stores.exists():
            store = request.user.stores.first()
            if store and hasattr(store, 'company'):
                efris_enabled = getattr(store.company, 'efris_enabled', False)
                vat_enabled = getattr(store.company, 'is_vat_enabled', False)

    # Prepare context for template
    context = {
        'sale': sale,
        'receipt': receipt,
        'is_duplicate': receipt.is_duplicate,
        'qr_image_src': qr_image_src,
        'qr_data': qr_data,  # Pass for debugging/display
        'total_paid': sale.total_amount,  # Assuming full payment for receipt
        'balance_due': 0,  # Assuming receipt is for completed sales
        'efris_and_vat_enabled': efris_enabled and vat_enabled,
        'efris_enabled': efris_enabled,
    }

    # Add store details
    if hasattr(sale.store, 'phone'):
        context['store_phone'] = sale.store.phone
    if hasattr(sale.store, 'address'):
        context['store_address'] = sale.store.address
    if hasattr(sale.store, 'tin'):
        context['store_tin'] = sale.store.tin

    # Add customer details
    if sale.customer:
        context['customer_name'] = sale.customer.name
        context['customer_phone'] = sale.customer.phone
        if hasattr(sale.customer, 'email'):
            context['customer_email'] = sale.customer.email
        if hasattr(sale.customer, 'tin'):
            context['customer_tin'] = sale.customer.tin

    # Add EFRIS verification URL if available
    if sale.is_fiscalized and sale.efris_invoice_number and hasattr(sale, 'verification_code'):
        try:
            store_config = sale.store.effective_efris_config if hasattr(sale.store, 'effective_efris_config') else {}
            is_production = store_config.get('is_production', False)

            if is_production:
                base_url = "https://efris.ura.go.ug/"
                context[
                    'efris_verification_url'] = f"{base_url}/site_mobile/#/invoiceValidation?invoiceNo={sale.efris_invoice_number}&antiFakeCode={sale.verification_code}"
            else:
                base_url = "https://efristest.ura.go.ug"
                context[
                    'efris_verification_url'] = f"{base_url}/site_new/#/invoiceValidation?invoiceNo={sale.efris_invoice_number}&antiFakeCode={sale.verification_code}"

        except Exception as e:
            # Log but continue without URL
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to generate EFRIS URL: {str(e)}")

    return render(request, 'sales/receipt.html', context)


@login_required
@permission_required("sales.add_sale", raise_exception=True)
def duplicate_sale(request, sale_id):
    """Duplicate an existing sale into a new draft sale"""
    original = get_object_or_404(Sale, pk=sale_id)

    # Optional: check user has access to this store
    if not request.user.is_superuser and original.store not in request.user.stores.all():
        messages.error(request, "You don't have access to this sale.")
        return redirect("sales:sales_list")

    with transaction.atomic():
        new_sale = Sale.objects.create(
            store=original.store,
            customer=original.customer,
            created_by=request.user,
            document_type=original.document_type,  # Copy document type
            payment_method=original.payment_method or Sale.PAYMENT_METHODS[0][0],
            duplicated_from=original,
            notes=f"Duplicated from {original.get_document_type_display().lower()} {original.document_number}"
        )

        for item in original.items.all():
            SaleItem.objects.create(
                sale=new_sale,
                product=item.product,
                service=item.service,  # Include service if present
                quantity=item.quantity,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
            )

    messages.success(request, f"{original.get_document_type_display()} {original.document_number} duplicated successfully.")
    return redirect("sales:sale_detail", pk=new_sale.pk)

@login_required
@permission_required("sales.view_sale", raise_exception=True)
def send_receipt(request, sale_id):
    """
    Send sale receipt via email to the customer
    """
    sale = get_object_or_404(
        Sale.objects.select_related('customer', 'store', 'created_by')
        .prefetch_related('items__product', 'payments'),
        pk=sale_id
    )

    # Check if the customer has an email
    if not sale.customer or not sale.customer.email:
        messages.error(request, "Cannot send receipt: customer has no email.")
        return redirect("sales:sale_detail", pk=sale_id)

    try:
        # Render HTML email template
        subject = f"{sale.get_document_type_display()} #{sale.document_number}"
        html_content = render_to_string("sales/email_receipt.html", {"sale": sale})

        # Create email
        email = EmailMessage(
            subject=subject,
            body=html_content,
            to=[sale.customer.email],
        )
        email.content_subtype = "html"  # Important for HTML email

        email.send(fail_silently=False)
        messages.success(request, f"{sale.get_document_type_display()} emailed successfully to {sale.customer.email}.")

    except Exception as e:
        messages.error(request, f"Error sending receipt: {str(e)}")

    return redirect("sales:sale_detail", pk=sale_id)

@csrf_exempt
@permission_required("sales.add_sale",raise_exception=True)
def api_create_sale(request):
    """API endpoint for creating sales"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)

        # Validate required fields
        required_fields = ['store_id', 'items', 'payment_method']
        for field in required_fields:
            if field not in data:
                return JsonResponse({'error': f'Missing required field: {field}'}, status=400)

        with transaction.atomic():
            # Create sale
            sale = Sale.objects.create(
                store_id=data['store_id'],
                created_by_id=data.get('user_id', 1),  # Default to admin
                customer_id=data.get('customer_id'),
                payment_method=data['payment_method'],
                notes=data.get('notes', ''),
                status__in=['COMPLETED', 'PAID']
            )

            # Add items
            for item_data in data['items']:
                product = Product.objects.get(id=item_data['product_id'])
                SaleItem.objects.create(
                    sale=sale,
                    product=product,
                    quantity=Decimal(str(item_data['quantity'])),
                    unit_price=Decimal(str(item_data.get('unit_price', product.selling_price))),
                    tax_rate=item_data.get('tax_rate', 'A')
                )

                # Update stock
                if product.track_stock:
                    product.stock_level -= Decimal(str(item_data['quantity']))
                    product.save()

            return JsonResponse({
                'success': True,
                'sale_id': sale.id,
                'invoice_number': sale.invoice_number,
                'total_amount': str(sale.total_amount)
            })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)