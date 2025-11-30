from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.generic import ListView, DetailView
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q, Sum, Count, Avg, F,Min
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.core.mail import EmailMessage
from django.http import HttpResponseServerError
from django.conf import settings
from django.core.exceptions import ValidationError, PermissionDenied
from decimal import Decimal, InvalidOperation
from django.core.paginator import Paginator
import json
import csv
from django.template.loader import render_to_string
import xlsxwriter
from io import BytesIO
from datetime import datetime, timedelta
import logging
from datetime import timedelta
from django.utils import timezone
from django_tenants.utils import tenant_context

from .models import Sale, SaleItem, Payment, Cart, CartItem, Receipt
from .forms import (
    SaleForm, SaleItemForm, PaymentForm, CartForm, QuickSaleForm,
    SaleSearchForm, RefundForm, ReceiptForm, BulkActionForm,
    SaleItemFormSet, PaymentFormSet
)
from inventory.models import Product, Stock, StockMovement
from customers.models import Customer
from stores.models import Store
from company.models import Company

logger = logging.getLogger(__name__)

@login_required
@require_POST
def create_customer_ajax(request):
    """
    Simplified customer creation for the current tenant company
    """
    try:
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip()
        address = request.POST.get('address', '').strip()
        customer_type = request.POST.get('customer_type', 'INDIVIDUAL').strip()
        tin = request.POST.get('tin', '').strip()
        nin = request.POST.get('nin', '').strip()
        from_efris = request.POST.get('from_efris', 'false') == 'true'

        logger.info(f"Creating customer: {name}, {phone}")

        # --- Validation ---
        if not name or not phone:
            return JsonResponse({
                'success': False,
                'error': 'Name and phone are required'
            })

        if Customer.objects.filter(phone=phone).exists():
            return JsonResponse({
                'success': False,
                'error': 'Customer with this phone number already exists'
            })

        # --- Get current company and store ---
        company = getattr(request, 'tenant', None)
        if not company:
            return JsonResponse({'success': False, 'error': 'No company context found'})

        store = Store.objects.filter(company=company).first()
        if not store:
            return JsonResponse({'success': False, 'error': 'No store available for this company'})

        # --- Create customer ---
        customer = Customer.objects.create(
            name=name,
            phone=phone,
            store=store,
            email=email or None,
            physical_address=address or None,
            customer_type=customer_type,
            tin=tin or None,
            nin=nin or None,
            efris_customer_type='2' if customer_type == 'BUSINESS' else '1'
        )

        logger.info(f"✅ Customer created: {customer.name} (ID: {customer.id})")

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
            }
        })

    except Exception as e:
        logger.error(f"❌ Error creating customer: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def search_products_and_services(request):
    """
    Combined search endpoint for both products and services
    """
    try:
        query = request.GET.get('q', '').strip()
        store_id = request.GET.get('store_id')
        item_type = request.GET.get('item_type', 'all')  # 'product', 'service', or 'all'

        if len(query) < 2 and item_type == 'all':
            return JsonResponse({'items': []})

        # Validate store access
        store = None
        if store_id:
            try:
                store_id = int(store_id)
                if request.user.is_superuser:
                    store = Store.objects.get(id=store_id)
                else:
                    store = Store.objects.filter(
                        Q(staff=request.user) | Q(company__staff=request.user),
                        id=store_id
                    ).first()
                    if not store:
                        return JsonResponse({'error': 'Access denied to store'}, status=403)
            except (ValueError, Store.DoesNotExist):
                return JsonResponse({'error': 'Invalid store'}, status=400)

        items_data = []

        # Search products if requested
        if item_type in ['product', 'all']:
            products = Product.objects.filter(
                is_active=True
            ).filter(
                Q(name__icontains=query) |
                Q(sku__icontains=query) |
                Q(barcode__icontains=query)
            ).select_related('category', 'supplier')

            # Filter by store stock if store is selected
            if store:
                products = products.filter(
                    store_inventory__store=store,
                    store_inventory__quantity__gt=0
                )

            products = products.distinct()[:15]

            for product in products:
                stock_info = None
                if store:
                    try:
                        stock = product.store_inventory.get(store=store)
                        stock_info = {
                            'available': float(stock.quantity),
                            'unit': product.unit_of_measure or 'pcs'
                        }
                    except product.store_inventory.model.DoesNotExist:
                        stock_info = {'available': 0, 'unit': product.unit_of_measure or 'pcs'}

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
                })

        # Search services if requested
        if item_type in ['service', 'all']:
            from inventory.models import Service

            services = Service.objects.filter(
                is_active=True
            ).filter(
                Q(name__icontains=query) |
                Q(code__icontains=query) |
                Q(description__icontains=query)
            ).select_related('category')

            services = services.distinct()[:15]

            for service in services:
                items_data.append({
                    'id': service.id,
                    'name': service.name,
                    'code': service.code or '',
                    'price': float(service.unit_price or 0),
                    'final_price': float(service.unit_price or 0),
                    'tax_rate': getattr(service, 'tax_rate', 'A'),
                    'unit_of_measure': service.unit_of_measure or '207',
                    'category': service.category.name if service.category else '',
                    'description': service.description or '',
                    'item_type': 'SERVICE',
                    'stock': None,  # Services don't have stock
                })

        return JsonResponse({'items': items_data})

    except Exception as e:
        logger.error(f"Error in combined search: {e}")
        return JsonResponse({'error': 'Search failed'}, status=500)


@login_required
def search_services(request):
    """
    AJAX endpoint for searching services (similar to product search)
    """
    try:
        query = request.GET.get('q', '').strip()
        store_id = request.GET.get('store_id')

        if len(query) < 2:
            return JsonResponse({'services': []})

        # Validate store access
        store = None
        if store_id:
            try:
                store_id = int(store_id)
                if request.user.is_superuser:
                    store = Store.objects.get(id=store_id)
                else:
                    store = Store.objects.filter(
                        Q(staff=request.user) | Q(company__staff=request.user),
                        id=store_id
                    ).first()
                    if not store:
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


class SalesListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Enhanced sales list with advanced filtering and pagination"""
    model = Sale
    template_name = 'sales/sales_list.html'
    context_object_name = 'sales'
    paginate_by = 25
    permission_required = 'sales.view_sale'

    def get_queryset(self):
        queryset = Sale.objects.select_related(
            'store', 'customer', 'created_by'
        ).prefetch_related('items', 'payments')

        # Filter by user's accessible stores
        if not self.request.user.is_superuser:
            user_stores = Store.objects.filter(
                staff=self.request.user
            ).distinct()
            queryset = queryset.filter(store__in=user_stores)

        form = SaleSearchForm(self.request.GET)
        if form.is_valid():
            search = form.cleaned_data.get('search')
            if search:
                queryset = queryset.filter(
                    Q(invoice_number__icontains=search) |
                    Q(transaction_id__icontains=search) |
                    Q(customer__name__icontains=search) |
                    Q(customer__phone__icontains=search) |
                    Q(efris_invoice_number__icontains=search)  # FIXED: Use efris_invoice_number from Sale
                )

            store = form.cleaned_data.get('store')
            if store:
                queryset = queryset.filter(store=store)

            transaction_type = form.cleaned_data.get('transaction_type')
            if transaction_type:
                queryset = queryset.filter(transaction_type=transaction_type)

            payment_method = form.cleaned_data.get('payment_method')
            if payment_method:
                queryset = queryset.filter(payment_method=payment_method)

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

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = SaleSearchForm(self.request.GET)
        context['bulk_form'] = BulkActionForm()

        # Add summary statistics
        queryset = self.get_queryset()
        context['stats'] = {
            'total_sales': queryset.count(),
            'total_amount': queryset.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
            'avg_amount': queryset.aggregate(Avg('total_amount'))['total_amount__avg'] or 0,
            'fiscalized_count': queryset.filter(is_fiscalized=True).count(),
        }

        return context


class SaleDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """Enhanced sale detail view with comprehensive information and EFRIS integration"""
    model = Sale
    template_name = 'sales/sales_detail.html'
    context_object_name = 'sale'
    permission_required = 'sales.view_sale'
    login_url = 'login'

    def get_object(self):
        sale = get_object_or_404(
            Sale.objects.select_related('store', 'customer', 'created_by')
            .prefetch_related('items__product', 'payments', 'receipt'),
            pk=self.kwargs['pk']
        )

        # Check user access to this sale
        if not self.request.user.is_superuser:
            user_stores = Store.objects.filter(
                Q(staff=self.request.user) |
                Q(company__staff=self.request.user)
            ).distinct()
            if sale.store not in user_stores:
                raise PermissionDenied("You don't have access to this sale.")

        return sale

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sale = self.object

        # Check company's EFRIS configuration for display context
        company = sale.store.company
        efris_enabled = getattr(company, 'efris_enabled', False)

        # Use the Sale model's EFRIS mixin methods for fiscalization checks
        can_fiscalize = False
        fiscalization_error = None

        if efris_enabled:
            # Use the mixin method can_fiscalize from the Sale model
            can_fiscalize, fiscalization_error = sale.can_fiscalize(self.request.user)

        # Check if sale has an associated invoice
        has_invoice = hasattr(sale, 'invoice') and sale.invoice is not None

        # Get fiscalization data - handle both Invoice and direct Sale fiscalization
        fiscal_data = self._get_fiscalization_data(sale, has_invoice)

        context.update({
            'refund_form': RefundForm(),
            'receipt_form': ReceiptForm(),
            'can_refund': sale.transaction_type == 'SALE' and not sale.is_refunded,
            'can_void': sale.transaction_type == 'SALE' and not sale.is_voided,
            'can_create_invoice': not has_invoice,
            'has_invoice': has_invoice,
            'can_fiscalize': can_fiscalize,
            'fiscalization_error': fiscalization_error,
            'efris_enabled': efris_enabled,
            'total_paid': sale.payments.filter(is_confirmed=True).aggregate(
                Sum('amount')
            )['amount__sum'] or 0,
            **fiscal_data  # Add all fiscal data to context
        })

        return context

    def _get_fiscalization_data(self, sale, has_invoice):
        """Extract fiscalization data from invoice or sale with proper URL handling"""
        fiscal_data = {
            'invoice_fiscalized': False,
            'fiscal_document_number': None,
            'fiscal_qr_code': None,
            'fiscal_verification_url': None,
            'fiscalization_time': None,
            'efris_invoice_no': None,
            'efris_invoice_id': None,
            'efris_antifake_code': None,
            'verification_code': None,
        }

        if has_invoice:
            invoice = sale.invoice
            fiscal_data.update(self._get_invoice_fiscal_data(invoice))
        elif sale.is_fiscalized:
            fiscal_data.update(self._get_sale_fiscal_data(sale))

        return fiscal_data

    def _get_invoice_fiscal_data(self, invoice):
        """Extract fiscal data from Invoice model"""
        data = {
            'invoice': invoice,
            'invoice_fiscalized': invoice.is_fiscalized,
            'fiscal_document_number': invoice.fiscal_document_number,
            'fiscal_qr_code': invoice.qr_code,
            'fiscal_verification_url': self._get_verification_url(
                invoice.fiscal_document_number,
                invoice.verification_code
            ),
            'fiscalization_time': invoice.fiscalization_time,
            'efris_invoice_no': invoice.fiscal_document_number,  # Same as fiscal_document_number
            'efris_invoice_id': getattr(invoice, 'efris_invoice_id', None),
            'efris_antifake_code': invoice.verification_code,  # Same as verification_code
            'verification_code': invoice.verification_code,
        }

        # If we have QR code data from EFRIS response, use it
        if hasattr(invoice, 'qr_code') and invoice.qr_code:
            # Check if QR code contains a URL (from EFRIS response)
            if invoice.qr_code.startswith('http'):
                data['fiscal_verification_url'] = invoice.qr_code
            # If QR code is just data, generate the URL
            elif invoice.fiscal_document_number and invoice.verification_code:
                data['fiscal_verification_url'] = self._get_verification_url(
                    invoice.fiscal_document_number,
                    invoice.verification_code
                )

        return data

    def _get_sale_fiscal_data(self, sale):
        """Extract fiscal data from Sale model (direct fiscalization)"""
        data = {
            'invoice_fiscalized': True,
            'fiscal_document_number': getattr(sale, 'efris_invoice_number', None),
            'fiscal_qr_code': getattr(sale, 'qr_code', None),
            'fiscal_verification_url': self._get_verification_url(
                getattr(sale, 'efris_invoice_number', None),
                getattr(sale, 'verification_code', None)
            ),
            'fiscalization_time': getattr(sale, 'fiscalization_time', None),
            'efris_invoice_no': getattr(sale, 'efris_invoice_number', None),
            'efris_invoice_id': getattr(sale, 'efris_invoice_id', None),
            'efris_antifake_code': getattr(sale, 'verification_code', None),
            'verification_code': getattr(sale, 'verification_code', None),
        }

        # If sale has QR code URL from EFRIS, use it
        qr_code = getattr(sale, 'qr_code', None)
        if qr_code and qr_code.startswith('http'):
            data['fiscal_verification_url'] = qr_code

        return data

    def _get_verification_url(self, invoice_no, verification_code):
        """Generate EFRIS verification URL for both test and production environments"""
        if not invoice_no or not verification_code:
            return None

        # Get company to check environment
        sale = self.object
        company = sale.store.company

        # Check if we're in test or production mode
        # You might want to add a field to Company model like 'efris_environment'
        is_production = getattr(company, 'efris_environment', 'test') == 'production'

        if is_production:
            # Production EFRIS URL
            base_url = "https://efris.ura.go.ug"
        else:
            # Test EFRIS URL (from your logs)
            base_url = "https://efristest.ura.go.ug"

        # URL format from your EFRIS response
        return f"{base_url}/site_new/#/invoiceValidation?invoiceNo={invoice_no}&antiFakeCode={verification_code}"

    def _get_legacy_verification_url(self, invoice_no, verification_code):
        """Alternative legacy URL format (if needed)"""
        if not invoice_no or not verification_code:
            return None

        sale = self.object
        company = sale.store.company
        is_production = getattr(company, 'efris_environment', 'test') == 'production'

        if is_production:
            base_url = "https://efris.ura.go.ug"
        else:
            base_url = "https://efristest.ura.go.ug"

        # Legacy URL format
        return f"{base_url}/return?invoiceNo={invoice_no}&code={verification_code}"

def should_create_invoice(sale, user):
    """
    Enhanced logic to determine if an invoice should be created for this sale.
    Now uses the Sale model's EFRIS mixin methods for better decision making.
    """
    if not sale.is_completed:
        return False

    company = sale.store.company
    with tenant_context(company):
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

    try:
        company = sale.store.company
        with tenant_context(company):

            # Check if invoice already exists
            if hasattr(sale, 'invoice') and sale.invoice:
                logger.warning(f"Invoice already exists for sale {sale.id}")
                return sale.invoice

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

            # ========== FIXED: Removed 'customer' field ==========
            # Create invoice with enhanced data
            invoice = Invoice.objects.create(
                sale=sale,
                store=sale.store,
                # customer=sale.customer,  # REMOVED - Invoice doesn't have customer field
                issue_date=timezone.now().date(),
                due_date=timezone.now().date() + timedelta(days=30),
                subtotal=sale.subtotal,
                tax_amount=sale.tax_amount,
                discount_amount=sale.discount_amount,
                total_amount=sale.total_amount,
                currency_code=sale.currency,
                business_type=business_type,
                operator_name=efris_basic_info.get('operator', user.get_full_name() or str(user)),
                created_by=user,
                status='SENT'  # Ready for fiscalization
            )
            # =====================================================

            logger.info(f"Created invoice {invoice.invoice_number} for sale {sale.id}")

            # Copy sale items to invoice items
            try:
                from invoices.models import InvoiceItem
                for sale_item in sale.items.all():
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        product=sale_item.product,
                        quantity=sale_item.quantity,
                        unit_price=sale_item.unit_price,
                        total_price=sale_item.total_price,
                        tax_amount=getattr(sale_item, 'tax_amount', 0),
                        discount_amount=getattr(sale_item, 'discount_amount', 0),
                    )
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
    """Create a new sale with improved error handling and EFRIS integration"""
    if request.method == 'GET':
        return render_sale_form(request)
    else:
        return process_sale_creation(request)




def render_sale_form(request):
    """Render the sale creation form with necessary context data"""
    # Filter stores based on user access
    if request.user.is_superuser:
        stores = Store.objects.filter(is_active=True)
    else:
        stores = Store.objects.filter(
            staff=request.user,
            is_active=True
        ).distinct()

    context = {
        'stores': stores,
        'page_title': 'Create New Sale',
        'form': SaleForm(user=request.user),
    }

    # Add default store if user has one
    if hasattr(request.user, 'default_store') and request.user.default_store:
        context['default_store'] = request.user.default_store


    return render(request, 'sales/create_sale.html', context)


@transaction.atomic
def process_sale_creation(request):
    sale = None
    try:
        logger.info(f"Processing sale creation for user {request.user.id}")

        # Validate and extract form data
        sale_data = validate_sale_data(request.POST, request.user)
        items_data = validate_items_data(request.POST.get('items_data', '[]'))

        if not items_data:
            messages.error(request, 'At least one item is required to create a sale.')
            return render_sale_form_with_errors(request)

        # Pre-validate stock availability for all items
        stock_validation_errors = validate_stock_availability(sale_data['store'], items_data)
        if stock_validation_errors:
            for error in stock_validation_errors:
                messages.error(request, error)
            return render_sale_form_with_errors(request)

        # Create the sale
        sale = create_sale_record(request, sale_data)

        # Add items to the sale (this will handle stock deduction automatically)
        create_sale_items(sale, items_data)
        sale.update_totals()  # This will calculate and save the correct totals

        # Now mark as completed
        sale.is_completed = True
        sale.save()

        # Handle payment if provided
        if request.POST.get('payment_amount'):
            handle_payment(sale, request.POST)

        # Create stock movement records
        create_stock_movements(sale)

        # Update sale totals (this will be done automatically by SaleItem.save())
        sale.refresh_from_db()

        # Enhanced invoice creation logic with EFRIS integration
        invoice_created = False
        if should_create_invoice(sale, request.user):
            try:
                invoice = create_invoice_for_sale(sale, request.user)
                invoice_created = True

                # Check if the invoice was automatically fiscalized
                if invoice.is_fiscalized:
                    messages.success(
                        request,
                        f'Invoice {invoice.invoice_number} created and fiscalized automatically!'
                    )
                else:
                    messages.info(
                        request,
                        f'Invoice {invoice.invoice_number} created. '
                        f'Visit the invoice detail page to fiscalize with EFRIS.'
                    )
            except Exception as e:
                logger.error(f"Failed to create invoice for sale {sale.id}: {e}")
                messages.warning(request, 'Sale created but invoice creation failed.')

        success_message = f'Sale #{sale.invoice_number} created successfully! Total amount: {sale.currency} {sale.total_amount:,.2f}'

        # Add EFRIS status information to success message
        company = sale.store.company
        if getattr(company, 'efris_enabled', False):
            if sale.is_fiscalized:
                success_message += ' Sale has been fiscalized with EFRIS.'
            elif invoice_created:
                success_message += ' Ready for EFRIS fiscalization.'

        messages.success(request, success_message)

        # Store sale ID for notification (outside transaction)
        sale_id = sale.id

        # Redirect based on action
        if 'save_draft' in request.POST:
            sale.is_completed = False
            sale.save()
            return redirect('invoices:sale_detail', pk=sale.pk)
        else:
            return redirect('sales:sale_detail', pk=sale.pk)

    except ValidationError as e:
        logger.error(f"Sale validation error: {e}")
        messages.error(request, f'Validation Error: {str(e)}')
        return render_sale_form_with_errors(request)
    except IntegrityError as e:
        logger.error(f"Database integrity error during sale creation: {e}")
        messages.error(request, 'A database error occurred. This might be due to concurrent access or data conflicts.')
        return render_sale_form_with_errors(request)
    except Exception as e:
        logger.error(f"Unexpected error in sale creation: {e}", exc_info=True)
        messages.error(request, 'An unexpected error occurred while creating the sale. Please try again.')
        return render_sale_form_with_errors(request)
    finally:
        # Create notification outside the transaction block to avoid transaction issues
        if sale and sale.id and sale.is_completed:
            try:
                from notifications.services import create_notification
                create_notification(
                    user=request.user,
                    notification_type='INFO',
                    title='Sale Completed',
                    message=f'Sale #{sale.invoice_number} has been completed successfully.',
                    event_type='sale_completed',
                    context_data={'sale_id': sale.id}
                )
            except Exception as e:
                logger.error(f"Failed to create notification for sale {sale.id}: {e}")
                # Don't fail the sale creation because of notification error

def validate_sale_data(post_data, user):
    """
    Enhanced sale data validation with customer EFRIS validation.
    Now uses Customer model's EFRIS mixins for validation.
    """
    required_fields = ['store', 'payment_method', 'transaction_type']

    for field in required_fields:
        if not post_data.get(field):
            raise ValidationError(f'{field.replace("_", " ").title()} is required.')

    # Validate store exists and user has access
    try:
        store = Store.objects.get(id=post_data['store'])
        if not store.is_active:
            raise ValidationError('Selected store is not active.')

        # Check user access
        if not user.is_superuser:
            user_stores = Store.objects.filter(
                Q(staff=user) | Q(company__staff=user)
            ).distinct()
            if store not in user_stores:
                raise ValidationError('You do not have access to the selected store.')

    except Store.DoesNotExist:
        raise ValidationError('Invalid store selected.')

    # Enhanced customer validation with EFRIS checks
    customer = None
    if post_data.get('customer'):
        try:
            customer = Customer.objects.get(id=post_data['customer'])

            # If company has EFRIS enabled, validate customer for EFRIS
            if getattr(store.company, 'efris_enabled', False):
                if hasattr(customer, 'validate_for_efris'):
                    is_valid, errors = customer.validate_for_efris()
                    if not is_valid:
                        error_msg = f"Customer EFRIS validation failed: {'; '.join(errors)}"
                        logger.warning(error_msg)
                        # Don't fail the sale, but log the warning

        except Customer.DoesNotExist:
            raise ValidationError('Invalid customer selected.')

    # Validate payment method
    valid_payment_methods = [choice[0] for choice in Sale.PAYMENT_METHODS]
    if post_data['payment_method'] not in valid_payment_methods:
        raise ValidationError(f'Invalid payment method. Valid options: {valid_payment_methods}')

    # Validate transaction type
    valid_transaction_types = [choice[0] for choice in Sale.TRANSACTION_TYPES]
    if post_data['transaction_type'] not in valid_transaction_types:
        raise ValidationError(f'Invalid transaction type. Valid options: {valid_transaction_types}')

    # Validate document type
    document_type = post_data.get('document_type', '').strip()
    if not document_type:
        document_type = 'ORIGINAL'
    else:
        valid_document_types = [choice[0] for choice in Sale.DOCUMENT_TYPES]
        if document_type not in valid_document_types:
            document_type = 'ORIGINAL'  # Default fallback

    # Validate discount amount
    try:
        discount_amount = Decimal(post_data.get('discount_amount', '0'))
        if discount_amount < 0:
            raise ValidationError('Discount amount cannot be negative.')
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Invalid discount amount.')

    return {
        'store': store,
        'customer': customer,
        'payment_method': post_data['payment_method'],
        'transaction_type': post_data['transaction_type'],
        'document_type': document_type,
        'currency': post_data.get('currency', 'UGX'),
        'discount_amount': discount_amount,
        'notes': post_data.get('notes', '').strip(),
    }


def validate_items_data(items_json):
    """
    Enhanced items validation supporting both products and services
    """
    try:
        items_data = json.loads(items_json) if items_json else []
    except (json.JSONDecodeError, ValueError, TypeError):
        raise ValidationError('Invalid items data format.')

    if not isinstance(items_data, list):
        raise ValidationError('Items data must be a list.')

    if not items_data:
        raise ValidationError('At least one item is required.')

    validated_items = []

    for i, item in enumerate(items_data):
        try:
            item_type = item.get('item_type', 'PRODUCT')

            if item_type == 'PRODUCT':
                # Validate product
                product_id = item.get('product_id')
                if not product_id:
                    raise ValidationError(f'Missing product_id in item {i + 1}.')

                try:
                    product = Product.objects.select_related('category', 'supplier').get(
                        id=product_id
                    )
                    if not product.is_active:
                        raise ValidationError(f'Product {product.name} is not active.')

                    # EFRIS validation for products if they support it
                    if hasattr(product, 'validate_for_efris_upload'):
                        is_valid, errors = product.validate_for_efris_upload()
                        if not is_valid:
                            logger.warning(f"Product EFRIS validation warning for {product.name}: {errors}")

                except Product.DoesNotExist:
                    raise ValidationError(f'Invalid product in item {i + 1}.')

                validated_item = {
                    'item_type': 'PRODUCT',
                    'product': product,
                    'service': None,
                }

            elif item_type == 'SERVICE':
                # Validate service
                service_id = item.get('service_id')
                if not service_id:
                    raise ValidationError(f'Missing service_id in item {i + 1}.')

                from inventory.models import Service
                try:
                    service = Service.objects.select_related('category').get(
                        id=service_id
                    )
                    if not service.is_active:
                        raise ValidationError(f'Service {service.name} is not active.')

                except Service.DoesNotExist:
                    raise ValidationError(f'Invalid service in item {i + 1}.')

                validated_item = {
                    'item_type': 'SERVICE',
                    'product': None,
                    'service': service,
                }
            else:
                raise ValidationError(f'Invalid item type in item {i + 1}: {item_type}')

            # Validate quantity
            try:
                quantity = Decimal(str(item.get('quantity', '0')))
                if quantity <= 0:
                    item_name = validated_item.get('product', validated_item.get('service')).name
                    raise ValidationError(f'Quantity for {item_name} must be greater than 0.')
            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError(f'Invalid quantity in item {i + 1}.')

            # Validate unit price
            try:
                unit_price = Decimal(str(item.get('unit_price', '0')))
                if unit_price < 0:
                    raise ValidationError(f'Unit price in item {i + 1} cannot be negative.')
            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError(f'Invalid unit price in item {i + 1}.')

            # Validate tax rate
            valid_tax_rates = [choice[0] for choice in SaleItem.TAX_RATE_CHOICES]
            tax_rate = item.get('tax_rate', 'A')
            if tax_rate not in valid_tax_rates:
                tax_rate = 'A'

            # Validate discount
            try:
                discount = Decimal(str(item.get('discount', '0')))
                if discount < 0 or discount > 100:
                    discount = Decimal('0')
            except (InvalidOperation, ValueError, TypeError):
                discount = Decimal('0')

            validated_item.update({
                'quantity': quantity,
                'unit_price': unit_price,
                'tax_rate': tax_rate,
                'discount': discount,
                'description': item.get('description', '').strip(),
            })

            validated_items.append(validated_item)

        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f'Error validating item {i + 1}: {str(e)}')

    return validated_items

def create_sale_record(request, sale_data):
    """Create the main Sale record - FIXED VERSION"""
    # Create sale with minimal data first
    sale = Sale.objects.create(
        store=sale_data['store'],
        created_by=request.user,
        customer=sale_data['customer'],
        transaction_type=sale_data['transaction_type'],
        document_type=sale_data['document_type'],
        payment_method=sale_data['payment_method'],
        currency=sale_data['currency'],
        discount_amount=sale_data['discount_amount'],
        notes=sale_data['notes'],
        is_completed=False,  # Set to False initially
        # Don't set totals here - let update_totals() calculate them
    )

    logger.info(f"Created sale {sale.id} by user {request.user.id}")
    return sale


def create_sale_items(sale, items_data):
    """
    Create SaleItem records for both products and services
    FIXED: Properly handle both products and services
    """
    for item_data in items_data:
        try:
            item_type = item_data.get('item_type', 'PRODUCT')

            # Get the product or service object
            product = item_data.get('product')
            service = item_data.get('service')

            # Validate that we have either product or service
            if not product and not service:
                raise ValidationError(f"Item data missing both product and service")

            # Get the item name for logging
            if product:
                item_name = product.name
            elif service:
                item_name = service.name
            else:
                item_name = "Unknown Item"

            # Create sale item with the appropriate product or service
            sale_item = SaleItem.objects.create(
                sale=sale,
                item_type=item_type,
                product=product,  # Will be None for services
                service=service,  # Will be None for products
                quantity=item_data['quantity'],
                unit_price=item_data['unit_price'],
                tax_rate=item_data.get('tax_rate', 'A'),
                discount=item_data.get('discount', 0),
                description=item_data.get('description', ''),
            )

            logger.info(
                f"Created sale item {sale_item.id} for sale {sale.id}: "
                f"{item_name} (Type: {item_type})"
            )

        except Exception as e:
            # Better error message with item details
            item_identifier = "Unknown"
            if item_data.get('product'):
                item_identifier = f"Product: {item_data['product'].name}"
            elif item_data.get('service'):
                item_identifier = f"Service: {item_data['service'].name}"

            logger.error(f"Error creating sale item for {item_identifier}: {e}", exc_info=True)
            raise ValidationError(f"Failed to create sale item for {item_identifier}: {str(e)}")

def handle_payment(sale, post_data):
    """Handle payment creation if payment information is provided"""
    try:
        payment_amount = post_data.get('payment_amount', '').strip()
        payment_reference = post_data.get('payment_reference', '').strip()

        if payment_amount:
            amount = Decimal(payment_amount)
            if amount > 0:
                Payment.objects.create(
                    sale=sale,
                    store=sale.store,
                    amount=amount,
                    payment_method=sale.payment_method,
                    transaction_reference=payment_reference,
                    is_confirmed=True,
                    confirmed_at=timezone.now(),
                )
                logger.info(f"Created payment {amount} for sale {sale.id}")
    except (InvalidOperation, ValueError, TypeError) as e:
        logger.warning(f"Invalid payment amount '{payment_amount}': {e}")
    except Exception as e:
        logger.error(f"Error creating payment for sale {sale.id}: {e}")


def create_stock_movements(sale):
    """Create stock movement records for product-based sale items only."""
    try:
        for item in sale.items.select_related('product'):

            # Skip services or invalid items
            if item.product is None:
                logger.warning(
                    f"Skipping stock movement for sale item {item.id} "
                    f"(Type: {item.item_type}) because it has no product."
                )
                continue

            StockMovement.objects.create(
                product=item.product,
                store=sale.store,
                movement_type='SALE',
                quantity=item.quantity,
                reference=sale.invoice_number or f"SALE-{sale.id}",
                unit_price=item.unit_price,
                total_value=item.total_price,
                created_by=sale.created_by,
                notes=f"Sale: {sale.invoice_number or sale.transaction_id}"
            )

            logger.info(
                f"Created stock movement for product '{item.product.name}' "
                f"in sale {sale.id}"
            )

    except Exception as e:
        logger.error(f"Error creating stock movements for sale {sale.id}: {e}")


def render_sale_form_with_errors(request):
    """Render the sale form with preserved data after errors"""
    if request.user.is_superuser:
        stores = Store.objects.filter(is_active=True)
    else:
        stores = Store.objects.filter(
            Q(staff=request.user) | Q(company__staff=request.user),
            is_active=True
        ).distinct()

    context = {
        'stores': stores,
        'page_title': 'Create New Sale',
        'form_data': request.POST,  # Preserve form data
        'form': SaleForm(user=request.user, data=request.POST),
    }

    return render(request, 'sales/create_sale.html', context)


@login_required
def search_products(request):
    try:
        query = request.GET.get('q', '').strip()
        store_id = request.GET.get('store_id')

        if len(query) < 2:
            return JsonResponse({'products': []})

        # Validate store access
        store = None
        if store_id:
            try:
                store_id = int(store_id)
                if request.user.is_superuser:
                    store = Store.objects.get(id=store_id)
                else:
                    store = Store.objects.filter(
                        Q(staff=request.user) | Q(company__staff=request.user),
                        id=store_id
                    ).first()
                    if not store:
                        return JsonResponse({'error': 'Access denied to store'}, status=403)
            except (ValueError, Store.DoesNotExist):
                return JsonResponse({'error': 'Invalid store'}, status=400)

        # Base product query
        products = Product.objects.filter(
            is_active=True
        ).filter(
            Q(name__icontains=query) |
            Q(sku__icontains=query) |
            Q(barcode__icontains=query)
        ).select_related('category', 'supplier')

        # Filter by store stock if store is selected
        if store:
            products = products.filter(
                store_inventory__store=store,
                store_inventory__quantity__gt=0
            )

        products = products.distinct()[:20]

        product_data = []
        for product in products:
            stock_info = None
            if store:
                try:
                    stock = product.store_inventory.get(store=store)
                    stock_info = {
                        'available': float(stock.quantity),
                        'unit': product.unit_of_measure or 'pcs'
                    }
                except product.store_inventory.model.DoesNotExist:
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
    try:
        query = request.GET.get('q', '').strip()

        if len(query) < 2:
            return JsonResponse({'customers': []})

        # Filter customers based on user access
        if request.user.is_superuser:
            customers = Customer.objects.filter(is_active=True)
        else:
            customers = Customer.objects.filter(
                Q(company__staff=request.user) | Q(created_by=request.user),
                is_active=True
            )

        customers = customers.filter(
            Q(name__icontains=query) |
            Q(phone__icontains=query) |
            Q(email__icontains=query) |
            Q(tin__icontains=query) |
            Q(nin__icontains=query) |
            Q(brn__icontains=query)
        )[:15]

        customer_data = []
        for customer in customers:
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
            })

        return JsonResponse({'customers': customer_data})

    except Exception as e:
        logger.error(f"Error in customer search: {e}")
        return JsonResponse({'error': 'Search failed'}, status=500)


@login_required
@permission_required('sales.add_sale', raise_exception=True)
def fiscalize_sale(request, sale_id):
    sale = get_object_or_404(
        Sale.objects.select_related('store__company', 'customer'),
        pk=sale_id
    )

    if not request.user.is_superuser:
        user_stores = Store.objects.filter(
            Q(staff=request.user) | Q(company__staff=request.user)
        ).distinct()
        if sale.store not in user_stores:
            messages.error(request, "You don't have access to this sale.")
            return redirect('sales:sales_list')

    company = sale.store.company

    if not getattr(company, 'efris_enabled', False):
        messages.error(request, 'EFRIS is not enabled for this company.')
        return redirect('sales:sale_detail', pk=sale_id)

    try:
        # Check if sale can be fiscalized
        if hasattr(sale, 'can_fiscalize'):
            can_fiscalize, reason = sale.can_fiscalize(request.user)
            if not can_fiscalize:
                messages.error(request, f'Cannot fiscalize sale: {reason}')
                return redirect('sales:sale_detail', pk=sale_id)

        invoice = None
        if hasattr(sale, 'invoice') and sale.invoice:
            invoice = sale.invoice
        else:
            try:
                invoice = create_invoice_for_sale(sale, request.user)
                messages.info(request, f'Invoice {invoice.invoice_number} created for fiscalization.')
            except Exception as e:
                logger.error(f"Failed to create invoice for sale {sale_id}: {e}")
                messages.error(request, 'Failed to create invoice for fiscalization.')
                return redirect('sales:sale_detail', pk=sale_id)

        if not invoice:
            messages.error(request, 'No invoice available for fiscalization.')
            return redirect('sales:sale_detail', pk=sale_id)

        # Check if already fiscalized
        if invoice.is_fiscalized:
            messages.warning(request, 'Invoice is already fiscalized.')
            return redirect('sales:sale_detail', pk=sale_id)

        try:
            from .tasks import fiscalize_invoice_async

            # Queue the task with proper error handling
            task_result = fiscalize_invoice_async.delay(invoice.pk, request.user.pk)

            messages.success(
                request,
                f'Fiscalization queued for invoice {invoice.invoice_number}. '
                f'Task ID: {task_result.id}. Please check back in a few moments.'
            )

            logger.info(
                f"Fiscalization task queued for sale {sale_id}, "
                f"invoice {invoice.pk}, task_id: {task_result.id}"
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
                        company = sale.store.company
                        if not getattr(company, 'efris_enabled', False):
                            error_messages.append(f"EFRIS not enabled for sale {sale.id}")
                            total_errors += 1
                            continue

                        # Check if sale can be fiscalized
                        if hasattr(sale, 'can_fiscalize'):
                            can_fiscalize, reason = sale.can_fiscalize(request.user)
                            if not can_fiscalize:
                                error_messages.append(f"Sale {sale.id}: {reason}")
                                total_errors += 1
                                continue

                        # Get or create invoice
                        invoice = None
                        if hasattr(sale, 'invoice') and sale.invoice:
                            invoice = sale.invoice
                        else:
                            # Create invoice if needed
                            if should_create_invoice(sale, request.user):
                                try:
                                    invoice = create_invoice_for_sale(sale, request.user)
                                except Exception as e:
                                    error_messages.append(f"Invoice creation failed for sale {sale.id}: {str(e)}")
                                    total_errors += 1
                                    continue

                        if not invoice:
                            error_messages.append(f"No invoice available for sale {sale.id}")
                            total_errors += 1
                            continue

                        # Skip if already fiscalized
                        if invoice.is_fiscalized:
                            continue

                        # FIXED: Queue fiscalization using correct task
                        from .tasks import fiscalize_invoice_async
                        fiscalize_invoice_async.delay(invoice.pk, request.user.pk)
                        total_queued += 1

                    except Exception as e:
                        logger.error(f"Error processing sale {sale.id} for bulk fiscalization: {e}")
                        error_messages.append(f"Sale {sale.id}: {str(e)}")
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
                        'receipt_number': f"RCP-{sale.invoice_number}",
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
    """
    Pre-validate stock availability for product items only
    Services don't have stock, so they're skipped
    """
    errors = []

    for item_data in items_data:
        # Only validate stock for products
        if item_data['item_type'] != 'PRODUCT' or not item_data.get('product'):
            continue

        try:
            stock = Stock.objects.select_for_update().filter(
                product=item_data['product'],
                store=store
            ).first()

            if not stock:
                errors.append(f'No stock record found for {item_data["product"].name} at {store.name}')
                continue

            available_quantity = stock.quantity
            requested_quantity = item_data['quantity']

            if available_quantity < requested_quantity:
                errors.append(
                    f'Insufficient stock for {item_data["product"].name}. '
                    f'Available: {available_quantity}, Requested: {requested_quantity}'
                )
        except Exception as e:
            logger.error(f"Stock validation error for product {item_data['product'].id}: {e}")
            errors.append(f'Stock validation failed for {item_data["product"].name}')

    return errors

@login_required
@permission_required('sales.view_sale', raise_exception=True)
def sales_efris_status(request):
    """
    Dashboard view showing EFRIS status for sales and invoices.
    """
    # Get user's accessible stores
    if request.user.is_superuser:
        stores = Store.objects.filter(is_active=True)
    else:
        stores = Store.objects.filter(
            Q(staff=request.user) | Q(company__staff=request.user),
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
        stores = Store.objects.all().distinct()
        return render(request, 'sales/select_store.html', {'stores': stores})

    store = get_object_or_404(
        Store.objects.filter(Q(staff=request.user)).distinct(),
        id=store_id
    )

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
        if request.user.is_superuser:
            stores = Store.objects.all().order_by('name')
        else:
            stores = Store.objects.filter(
                Q(staff=request.user) | Q(company__staff=request.user)
            ).distinct().order_by('name')

        # Get customers from stores user has access to
        if request.user.is_superuser:
            customers = Customer.objects.all().order_by('name')[:100]
        else:
            customers = Customer.objects.filter(
                company__staff=request.user
            ).distinct().order_by('name')[:100]

        # Add EFRIS status information to context
        context = {
            'stores': stores,
            'customers': customers,
        }

        # Add EFRIS configuration info for stores
        efris_stores = []
        for store in stores:
            store_info = {
                'id': store.id,
                'name': store.name,
                'efris_enabled': getattr(store.company, 'efris_enabled', False),
                'auto_create_invoices': getattr(store.company, 'auto_create_invoices', False),
                'auto_fiscalize': getattr(store.company, 'auto_fiscalize', False),
            }
            efris_stores.append(store_info)

        context['efris_stores'] = efris_stores

        return render(request, 'sales/quick_sale.html', context)

    # Handle POST request - keeping existing logic
    return JsonResponse({'success': False, 'error': 'POST handler not implemented in this snippet'})


@login_required
@permission_required("sales.add_sale", raise_exception=True)
@require_http_methods(["GET", "POST"])
def process_refund(request, sale_id):
    """Enhanced refund processing with dedicated template and comprehensive validation"""
    sale = get_object_or_404(
        Sale.objects.select_related('store', 'customer', 'created_by')
        .prefetch_related('items__product', 'payments'),
        pk=sale_id
    )

    # Check user access to this sale
    if not request.user.is_superuser:
        user_stores = Store.objects.filter(
            Q(staff=request.user) | Q(company__staff=request.user)
        ).distinct()
        if sale.store not in user_stores:
            messages.error(request, "You don't have access to this sale.")
            return redirect('sales:sales_list')

    # Check if sale can be refunded
    if sale.transaction_type != 'SALE':
        messages.error(request, 'Only regular sales can be refunded.')
        return redirect('sales:sale_detail', pk=sale_id)

    if sale.is_refunded:
        messages.warning(request, 'This sale has already been refunded.')
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
                item_key = refund_item.product.id
                if item_key not in refunded_items:
                    refunded_items[item_key] = Decimal('0')
                refunded_items[item_key] += abs(refund_item.quantity)

        # Prepare items data for template
        items_data = []
        for item in sale.items.all():
            refunded_qty = refunded_items.get(item.product.id, Decimal('0'))
            available_qty = item.quantity - refunded_qty

            if available_qty > 0:
                items_data.append({
                    'id': item.id,
                    'product': item.product,
                    'original_quantity': item.quantity,
                    'refunded_quantity': refunded_qty,
                    'available_quantity': available_qty,
                    'unit_price': item.unit_price,
                    'line_total': getattr(item, 'line_total', item.quantity * item.unit_price),
                    'available_refund_amount': available_qty * item.unit_price,
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

    # POST request processing would go here
    return JsonResponse({'success': False, 'error': 'POST refund processing not implemented in this snippet'})


@permission_required('sales.view_sale', raise_exception=True)
def export_sales(request, sales, format_type):
    """Export sales data"""
    if format_type == 'export_csv':
        response = HttpResponse(content_type='text/csv')
        response[
            'Content-Disposition'] = f'attachment; filename="sales_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Invoice Number', 'Transaction ID', 'Date', 'Customer', 'Store',
            'Payment Method', 'Subtotal', 'Tax', 'Discount', 'Total', 'Status'
        ])

        for sale in sales:
            writer.writerow([
                sale.invoice_number,
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
            'Invoice Number', 'Transaction ID', 'Date', 'Customer', 'Store',
            'Payment Method', 'Subtotal', 'Tax', 'Discount', 'Total', 'Status'
        ]

        for col, header in enumerate(headers):
            worksheet.write(0, col, header)

        # Add data
        for row, sale in enumerate(sales, 1):
            worksheet.write(row, 0, sale.invoice_number)
            worksheet.write(row, 1, str(sale.transaction_id))
            worksheet.write(row, 2, sale.created_at.strftime('%Y-%m-%d %H:%M:%S'))
            worksheet.write(row, 3, sale.customer.name if sale.customer else 'Walk-in')
            worksheet.write(row, 4, sale.store.name)
            worksheet.write(row, 5, sale.get_payment_method_display())
            worksheet.write(row, 6, float(sale.subtotal))
            worksheet.write(row, 7, float(sale.tax_amount))
            worksheet.write(row, 8, float(sale.discount_amount))
            worksheet.write(row, 9, float(sale.total_amount))
            worksheet.write(row, 10, 'Fiscalized' if sale.is_fiscalized else 'Not Fiscalized')

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

            logger.debug(f"Queryset count after date filter: {queryset.count()}")
        except Exception as e:
            logger.error(f"Error applying date filter: {e}")
            return JsonResponse({'error': 'Date filter error'}, status=500)

        # Apply other filters
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)

        if payment_method:
            queryset = queryset.filter(payment_method=payment_method)

        if search:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search) |
                Q(transaction_id__icontains=search) |
                Q(customer__name__icontains=search) |
                Q(customer__phone__icontains=search)
            ).distinct()

        # Order by creation date (newest first)
        queryset = queryset.order_by('-created_at')

        # Calculate statistics
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_sales = queryset.filter(created_at__gte=today_start)
        today_stats = today_sales.aggregate(
            count=Count('id'),
            revenue=Sum('total_amount'),
            fiscalized_count=Count('id', filter=Q(is_fiscalized=True))
        )

        overall_stats = queryset.aggregate(avg_amount=Avg('total_amount'))

        stats = {
            'today_count': today_stats['count'] or 0,
            'today_revenue': float(today_stats['revenue'] or 0),
            'avg_amount': float(overall_stats['avg_amount'] or 0),
            'fiscalized_count': today_stats['fiscalized_count'] or 0
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
                }

            sale_data = {
                'id': sale.id,
                'invoice_number': getattr(sale, 'invoice_number', ''),
                'transaction_id': str(getattr(sale, 'transaction_id', '')),
                'created_at': sale.created_at.isoformat() if sale.created_at else '',
                'customer': customer_data,
                'payment_method': getattr(sale, 'payment_method', ''),
                'payment_method_display': getattr(sale, 'get_payment_method_display', lambda: '')(),
                'transaction_type': getattr(sale, 'transaction_type', ''),
                'transaction_type_display': getattr(sale, 'get_transaction_type_display', lambda: '')(),
                'total_amount': float(getattr(sale, 'total_amount', 0)),
                'is_fiscalized': getattr(sale, 'is_fiscalized', False),
                'is_refunded': getattr(sale, 'is_refunded', False),
                'is_voided': getattr(sale, 'is_voided', False),
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
            'per_page': per_page
        }

        response_data = {
            'sales': sales_data,
            'stats': stats,
            'pagination': pagination
        }

        logger.info(f"Successfully returning {len(sales_data)} sales records for store {store_id}")
        return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"Unexpected error in store_sales_api: {e}", exc_info=True)
        return JsonResponse({
            'error': 'An unexpected error occurred while fetching sales data',
            'details': str(e)
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

        # Base queryset with optimizations
        sales_qs = Sale.objects.filter(
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
            transaction_type='SALE',
            is_voided=False
        ).select_related('store', 'customer').prefetch_related('items__product', 'items__service', 'payments')

        # Filter by store if specified
        if store_id and store_id != '':
            sales_qs = sales_qs.filter(store_id=store_id)

        # Get user's accessible stores for filter dropdown
        if request.user.is_superuser:
            stores = Store.objects.filter(is_active=True).order_by('name')
        else:
            stores = Store.objects.filter(
                Q(staff=request.user) | Q(company__staff=request.user),
                is_active=True
            ).distinct().order_by('name')

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
            'top_items': top_items,  # Changed from top_products to top_items
            'hourly_sales': hourly_data,

            # Additional insights
            'sales_growth': sales_growth_display,
            'new_customers': new_customers,
            'return_rate': return_rate_display,

            # Filter options
            'stores': stores,
            'selected_store': store_id,

            # Additional analytics
            'store_performance': store_performance,
            'payment_efficiency': payment_efficiency,
            'item_type_breakdown': item_type_breakdown,  # NEW

            # Period information
            'period_days': (date_to - date_from).days + 1,
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

        if request.user.is_superuser:
            stores = Store.objects.filter(is_active=True).order_by('name')
        else:
            stores = Store.objects.filter(
                Q(staff=request.user) | Q(company__staff=request.user),
                is_active=True
            ).distinct().order_by('name')

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
    """Enhanced void sale functionality with dedicated template"""
    sale = get_object_or_404(
        Sale.objects.select_related('store', 'customer', 'created_by')
        .prefetch_related('items__product', 'payments'),
        pk=sale_id
    )

    # Check user access to this sale
    if not request.user.is_superuser:
        user_stores = Store.objects.filter(
            Q(staff=request.user) | Q(company__staff=request.user)
        ).distinct()
        if sale.store not in user_stores:
            messages.error(request, "You don't have access to this sale.")
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
    max_void_days = getattr(settings, 'MAX_SALE_VOID_DAYS', 7)  # Default 7 days
    if (timezone.now().date() - sale.created_at.date()).days > max_void_days:
        messages.error(request, f'Sales older than {max_void_days} days cannot be voided.')
        return redirect('sales:sale_detail', pk=sale_id)

    # GET request - show void confirmation form
    if request.method == 'GET':
        # Calculate impact of voiding
        total_payments = sale.payments.filter(is_confirmed=True).aggregate(
            Sum('amount')
        )['amount__sum'] or Decimal('0')

        context = {
            'sale': sale,
            'total_payments': total_payments,
            'items_count': sale.items.count(),
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
            original_invoice = sale.invoice_number

            # Restore stock for all items
            for item in sale.items.all():
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
                        quantity=item.quantity,  # Positive for incoming
                        reference=f"VOID-{sale.invoice_number or sale.id}",
                        unit_price=item.unit_price,
                        total_value=item.line_total,
                        created_by=request.user,
                        notes=f'Void sale: {original_invoice}, Reason: {void_reason}'
                    )

                except Stock.DoesNotExist:
                    logger.warning(f"No stock record found for {item.product.name} at {sale.store.name}")
                    # Create stock record if it doesn't exist
                    Stock.objects.create(
                        product=item.product,
                        store=sale.store,
                        quantity=item.quantity,
                        last_updated=timezone.now()
                    )

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
            sale.save()

            # Create audit log entry
            logger.info(
                f"Sale voided: ID={sale.id}, Invoice={original_invoice}, "
                f"Amount={original_total}, Reason={void_reason}, "
                f"User={request.user.id}, Items={sale.items.count()}, "
                f"Payments={voided_payments_count}"
            )

            messages.success(
                request,
                f'Sale #{original_invoice} has been voided successfully. '
                f'Stock has been restored and payments have been marked as voided.'
            )

            return redirect('sales:sale_detail', pk=sale.pk)

    except Exception as e:
        logger.error(f"Error voiding sale {sale_id}: {e}", exc_info=True)
        messages.error(request, 'An error occurred while voiding the sale. Please try again.')
        return redirect('sales:void_sale', sale_id=sale_id)


@login_required
@permission_required('sales.view_sale', raise_exception=True)
def print_receipt(request, sale_id):
    """Generate and print receipt - supports both products and services"""
    sale = get_object_or_404(Sale, id=sale_id)

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

    # Get or create receipt
    receipt, created = Receipt.objects.get_or_create(
        sale=sale,
        defaults={
            'receipt_number': f"RCP-{sale.invoice_number}",
            'printed_by': request.user,
            'receipt_data': {
                'sale_data': {
                    'invoice_number': sale.invoice_number,
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
                    'verification_code': sale.verification_code or '',
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
        }
    )

    if not created:
        receipt.print_count += 1
        receipt.is_duplicate = True
        receipt.save()

    context = {
        'sale': sale,
        'receipt': receipt,
        'is_duplicate': receipt.is_duplicate,
    }

    return render(request, 'sales/receipt.html', context)

@login_required
@permission_required("sales.add_sale", raise_exception=True)
def duplicate_sale(request, sale_id):
    """Duplicate an existing sale into a new draft sale"""
    original = get_object_or_404(Sale, pk=sale_id)

    # Optional: check user has access to this store
    if not request.user.is_superuser and original.store not in request.user.stores.all():
        messages.error(request, "You don’t have access to this sale.")
        return redirect("sales:sales_list")

    with transaction.atomic():
        new_sale = Sale.objects.create(
            store=original.store,
            customer=original.customer,
            created_by=request.user,
            transaction_type="SALE",
            payment_method=original.payment_method or Sale.PAYMENT_METHODS[0][0],
            duplicated_from=original,
            notes=f"Duplicated from sale {original.invoice_number}"
        )

        for item in original.items.all():
            SaleItem.objects.create(
                sale=new_sale,
                product=item.product,
                quantity=item.quantity,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
            )

    messages.success(request, f"Sale {original.invoice_number} duplicated successfully.")
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
        subject = f"Receipt for Sale #{sale.invoice_number}"
        html_content = render_to_string("sales/email_receipt.html", {"sale": sale})

        # Create email
        email = EmailMessage(
            subject=subject,
            body=html_content,
            to=[sale.customer.email],
        )
        email.content_subtype = "html"  # Important for HTML email

        email.send(fail_silently=False)
        messages.success(request, f"Receipt emailed successfully to {sale.customer.email}.")

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
                is_completed=True
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
