from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.urls import reverse_lazy, reverse
from django.db.models import Q, Sum, Count, F, Avg, ExpressionWrapper, DurationField, Prefetch
from django.utils import timezone
from django.db import transaction, connection
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django_tenants.utils import schema_context, get_tenant_model
from weasyprint import HTML
from datetime import timedelta, datetime
from decimal import Decimal
import json
import csv
import logging

from .models import (
    Invoice, InvoiceTemplate, InvoicePayment,
    PaymentSchedule, PaymentReminder, PaymentAllocation
)
from .forms import (
    InvoiceForm, InvoiceSearchForm, InvoicePaymentForm,
    InvoiceTemplateForm, BulkInvoiceActionForm, FiscalizationForm,
    PaymentScheduleForm, PaymentReminderForm
)
from sales.models import Sale, SaleItem, Payment
from customers.models import Customer
from inventory.models import Product, Service, Stock
from stores.utils import get_user_accessible_stores, validate_store_access
from efris.models import FiscalizationAudit

logger = logging.getLogger(__name__)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_current_tenant(request):
    """Get current tenant from request - tenant-safe"""
    return getattr(request, 'tenant', None)


def get_tenant_invoices_queryset(request, base_filters=None):
    """
    Get tenant-specific invoice queryset with proper filtering

    Args:
        request: HTTP request object
        base_filters: Additional Q objects for filtering

    Returns:
        QuerySet of invoices for current tenant
    """
    # Get tenant from connection schema
    tenant = get_current_tenant(request)

    if not tenant:
        return Invoice.objects.none()

    # Base queryset with tenant filtering
    queryset = Invoice.objects.select_related(
        'sale',
        'sale__customer',
        'sale__created_by',
        'sale__store',
        'sale__store__company',
        'created_by',
        'fiscalized_by'
    ).prefetch_related(
        Prefetch(
            'payments',
            queryset=InvoicePayment.objects.select_related('processed_by')
        ),
        Prefetch(
            'payment_schedules',
            queryset=PaymentSchedule.objects.all()
        ),
        Prefetch(
            'reminders',
            queryset=PaymentReminder.objects.order_by('-sent_at')
        )
    )

    # Apply base filters if provided
    if base_filters:
        queryset = queryset.filter(base_filters)

    return queryset


# ============================================================================
# INVOICE LIST & DASHBOARD VIEWS
# ============================================================================

@login_required
@permission_required('invoices.view_invoice', raise_exception=True)
def invoice_list(request):
    """Enhanced invoice list with filtering, search, and tenant isolation"""

    # Get accessible stores for user
    stores = get_user_accessible_stores(request.user)

    if not stores or not stores.exists():
        messages.error(request, "You don't have access to any stores")
        return redirect('dashboard:home')

    # Get filter parameters
    status_filter = request.GET.getlist('status')
    payment_status = request.GET.getlist('payment_status')
    search_query = request.GET.get('search', '').strip()
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    customer_filter = request.GET.get('customer', '')
    store_filter = request.GET.get('store', '')
    fiscalization_status = request.GET.get('fiscalization_status', '')
    overdue_only = request.GET.get('overdue_only', '') == 'on'

    # Base queryset with tenant filtering
    invoices = get_tenant_invoices_queryset(
        request,
        base_filters=Q(store__in=stores)
    )

    # Apply filters
    if status_filter:
        invoices = invoices.filter(sale__status__in=status_filter)

    if payment_status:
        invoices = invoices.filter(sale__payment_status__in=payment_status)

    if fiscalization_status:
        invoices = invoices.filter(fiscalization_status=fiscalization_status)

    if search_query:
        invoices = invoices.filter(
            Q(sale__document_number__icontains=search_query) |
            Q(sale__customer__name__icontains=search_query) |
            Q(fiscal_document_number__icontains=search_query) |
            Q(sale__customer__phone__icontains=search_query) |
            Q(sale__customer__email__icontains=search_query)
        )

    if date_from:
        try:
            date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d').date()
            invoices = invoices.filter(sale__created_at__date__gte=date_from_parsed)
        except ValueError:
            messages.warning(request, "Invalid 'from' date format")

    if date_to:
        try:
            date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d').date()
            invoices = invoices.filter(sale__created_at__date__lte=date_to_parsed)
        except ValueError:
            messages.warning(request, "Invalid 'to' date format")

    if customer_filter:
        invoices = invoices.filter(sale__customer_id=customer_filter)

    if store_filter:
        invoices = invoices.filter(store_id=store_filter)

    if overdue_only:
        today = timezone.now().date()
        invoices = invoices.filter(
            sale__due_date__lt=today,
            sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
        )

    # Order by most recent
    invoices = invoices.order_by('-sale__created_at')

    # Pagination
    paginator = Paginator(invoices, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Statistics
    stats = {
        'total_invoices': invoices.count(),
        'draft_count': invoices.filter(sale__status='DRAFT').count(),
        'pending_count': invoices.filter(sale__status='PENDING_PAYMENT').count(),
        'paid_count': invoices.filter(sale__status__in=['PAID', 'COMPLETED']).count(),
        'partially_paid_count': invoices.filter(sale__payment_status='PARTIALLY_PAID').count(),
        'overdue_count': invoices.filter(sale__payment_status='OVERDUE').count(),
        'total_amount': invoices.aggregate(
            total=Sum('sale__total_amount')
        )['total'] or Decimal('0'),
        'paid_amount': invoices.filter(
            sale__status__in=['PAID', 'COMPLETED']
        ).aggregate(
            total=Sum('sale__total_amount')
        )['total'] or Decimal('0'),
        'outstanding_amount': invoices.filter(
            sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
        ).aggregate(
            total=Sum('sale__total_amount')
        )['total'] or Decimal('0'),
        'fiscalized_count': invoices.filter(is_fiscalized=True).count(),
        'pending_fiscalization': invoices.filter(
            fiscalization_status='pending',
            sale__status__in=['COMPLETED', 'PAID']
        ).count(),
    }

    # Get customers and stores for filters
    customers = Customer.objects.filter(
        sales__store__in=stores
    ).distinct().order_by('name')

    context = {
        'page_obj': page_obj,
        'invoices': page_obj.object_list,
        'stats': stats,
        'customers': customers,
        'stores': stores,
        'status_filter': status_filter,
        'payment_status': payment_status,
        'fiscalization_status': fiscalization_status,
        'search_query': search_query,
        'date_from': date_from,
        'date_to': date_to,
        'customer_filter': customer_filter,
        'store_filter': store_filter,
        'overdue_only': overdue_only,
    }

    return render(request, 'invoices/invoice_list.html', context)


@login_required
@permission_required('invoices.view_invoice', raise_exception=True)
def invoice_dashboard(request):
    """Enhanced dashboard with partial payment tracking"""

    stores = get_user_accessible_stores(request.user)

    if not stores or not stores.exists():
        messages.error(request, "You don't have access to any stores")
        return redirect('dashboard:home')

    today = timezone.now().date()
    this_month_start = today.replace(day=1)

    # Base queryset
    invoices = get_tenant_invoices_queryset(
        request,
        base_filters=Q(store__in=stores)
    )

    # Key Metrics
    total_invoices = invoices.count()
    invoices_this_month = invoices.filter(
        sale__created_at__date__gte=this_month_start
    ).count()

    total_revenue = invoices.filter(
        sale__status__in=['PAID', 'COMPLETED']
    ).aggregate(total=Sum('sale__total_amount'))['total'] or Decimal('0')

    pending_amount = invoices.filter(
        sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
    ).aggregate(total=Sum('sale__total_amount'))['total'] or Decimal('0')

    overdue_invoices = invoices.filter(
        sale__due_date__lt=today,
        sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
    ).count()

    fiscalized_count = invoices.filter(is_fiscalized=True).count()
    fiscalization_rate = (fiscalized_count / total_invoices * 100) if total_invoices > 0 else 0

    # Partial Payment Metrics
    partially_paid_invoices = invoices.filter(
        sale__payment_status='PARTIALLY_PAID'
    )

    partially_paid_count = partially_paid_invoices.count()
    partially_paid_total = partially_paid_invoices.aggregate(
        total=Sum('sale__total_amount')
    )['total'] or Decimal('0')

    # Payment schedules summary
    overdue_schedules = PaymentSchedule.objects.filter(
        invoice__store__in=stores,
        status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE'],
        due_date__lt=today
    ).count()

    upcoming_schedules = PaymentSchedule.objects.filter(
        invoice__store__in=stores,
        status__in=['PENDING', 'PARTIALLY_PAID'],
        due_date__range=[today, today + timedelta(days=7)]
    ).select_related('invoice__sale__customer').order_by('due_date')[:10]

    # Recent activity
    recent_invoices = invoices.order_by('-sale__created_at')[:10]

    recent_payments = InvoicePayment.objects.filter(
        invoice__store__in=stores
    ).select_related(
        'invoice__sale__customer',
        'processed_by'
    ).order_by('-created_at')[:10]

    # Top customers by outstanding amount
    top_debtors = invoices.filter(
        sale__customer__isnull=False,
        sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
    ).values(
        'sale__customer__id',
        'sale__customer__name'
    ).annotate(
        total_outstanding=Sum('sale__total_amount') - Sum('payments__amount'),
        invoice_count=Count('id')
    ).order_by('-total_outstanding')[:5]

    context = {
        'metrics': {
            'total_invoices': total_invoices,
            'invoices_this_month': invoices_this_month,
            'total_revenue': total_revenue,
            'pending_amount': pending_amount,
            'overdue_invoices': overdue_invoices,
            'fiscalized_count': fiscalized_count,
            'fiscalization_rate': round(fiscalization_rate, 1),
            'partially_paid_count': partially_paid_count,
            'partially_paid_total': partially_paid_total,
            'overdue_schedules': overdue_schedules,
        },
        'recent_invoices': recent_invoices,
        'recent_payments': recent_payments,
        'upcoming_schedules': upcoming_schedules,
        'top_debtors': top_debtors,
        'stores': stores,
    }

    return render(request, 'invoices/dashboard.html', context)


# ============================================================================
# INVOICE DETAIL & CRUD VIEWS
# ============================================================================

@login_required
@permission_required('invoices.view_invoice', raise_exception=True)
def invoice_detail(request, pk):
    """Enhanced invoice detail with partial payment tracking"""

    stores = get_user_accessible_stores(request.user)

    invoice = get_object_or_404(
        get_tenant_invoices_queryset(request, base_filters=Q(store__in=stores)),
        pk=pk
    )

    # Validate store access
    try:
        validate_store_access(request.user, invoice.store, 'view', raise_exception=True)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('invoices:list')

    # Get payment schedules
    payment_schedules = invoice.payment_schedules.all().order_by('installment_number')

    # Get payment history with allocations
    payments = invoice.payments.select_related(
        'processed_by'
    ).prefetch_related(
        'allocations__payment_schedule'
    ).order_by('-created_at')

    # Get reminders
    reminders = invoice.reminders.select_related('sent_by').order_by('-sent_at')[:10]

    # Check permissions
    can_edit, edit_message = invoice.can_edit()
    can_cancel, cancel_message = invoice.can_cancel()
    can_fiscalize, fiscalize_message = invoice.can_fiscalize(request.user)

    # Stock availability
    stock_availability = invoice.stock_availability

    # Payment forms
    payment_form = InvoicePaymentForm(invoice=invoice)
    schedule_form = PaymentScheduleForm()
    reminder_form = PaymentReminderForm()

    # Next payment due
    next_payment_due = invoice.next_payment_due

    # Fiscalization audit history
    fiscalization_audits = invoice.fiscalization_audits.select_related(
        'user'
    ).order_by('-timestamp')[:10]

    context = {
        'invoice': invoice,
        'sale': invoice.sale,
        'items': invoice.sale.items.select_related('product', 'service'),
        'payment_schedules': payment_schedules,
        'payments': payments,
        'reminders': reminders,
        'stock_availability': stock_availability,
        'can_edit': can_edit,
        'edit_message': edit_message,
        'can_cancel': can_cancel,
        'cancel_message': cancel_message,
        'can_fiscalize': can_fiscalize,
        'fiscalize_message': fiscalize_message,
        'payment_form': payment_form,
        'schedule_form': schedule_form,
        'reminder_form': reminder_form,
        'next_payment_due': next_payment_due,
        'fiscalization_audits': fiscalization_audits,
        'payment_completion_percentage': invoice.payment_completion_percentage,
        'has_overdue_payments': invoice.has_overdue_payments,
    }

    return render(request, 'invoices/invoice_detail.html', context)


@login_required
@permission_required('invoices.add_invoice', raise_exception=True)
def invoice_create(request):
    """Create new invoice with support for payment schedules"""

    stores = get_user_accessible_stores(request.user)

    if not stores or not stores.exists():
        messages.error(request, "You don't have access to any stores")
        return redirect('dashboard:home')

    # If queryset, get first store
    store = stores.first() if hasattr(stores, 'first') else stores

    try:
        validate_store_access(request.user, store, 'create', raise_exception=True)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('invoices:list')

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get form data
                customer_id = request.POST.get('customer')
                due_date = request.POST.get('due_date')
                terms = request.POST.get('terms', '')
                purchase_order = request.POST.get('purchase_order', '')
                notes = request.POST.get('notes', '')

                # Payment schedule options
                enable_payment_schedule = request.POST.get('enable_payment_schedule') == 'on'
                installments = int(request.POST.get('installments', 1))

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

                # Create payment schedule if enabled
                if enable_payment_schedule and installments > 1:
                    invoice.create_payment_schedule(
                        installments=installments,
                        first_due_date=sale.due_date
                    )
                    messages.info(
                        request,
                        f'Payment schedule created with {installments} installments'
                    )

                messages.success(
                    request,
                    f'Invoice {sale.document_number} created successfully'
                )
                return redirect('invoices:detail', pk=invoice.pk)

        except Exception as e:
            logger.error(f"Error creating invoice: {e}", exc_info=True)
            messages.error(request, f"Error creating invoice: {str(e)}")

    # GET request - show form
    customers = Customer.objects.filter(
        is_active=True
    ).order_by('name')

    # Get products and services
    products = Product.objects.filter(
        is_active=True
    ).select_related('category').values(
        'id', 'name', 'sku', 'selling_price', 'tax_rate', 'unit_of_measure'
    )

    services = Service.objects.filter(
        is_active=True
    ).values(
        'id', 'name', 'code', 'price', 'tax_rate', 'unit_of_measure'
    )

    context = {
        'customers': customers,
        'products': list(products),
        'services': list(services),
        'store': store,
        'stores': stores,
        'default_due_date': (timezone.now().date() + timedelta(days=30)).strftime('%Y-%m-%d'),
    }

    return render(request, 'invoices/invoice_create.html', context)


# ============================================================================
# PAYMENT MANAGEMENT VIEWS
# ============================================================================

@login_required
@permission_required('invoices.add_invoicepayment', raise_exception=True)
def add_payment(request, pk):
    """Add payment to invoice with allocation to schedules"""

    stores = get_user_accessible_stores(request.user)

    invoice = get_object_or_404(
        get_tenant_invoices_queryset(request, base_filters=Q(store__in=stores)),
        pk=pk
    )

    try:
        validate_store_access(request.user, invoice.store, 'edit', raise_exception=True)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=403)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                payment_amount = Decimal(request.POST.get('amount', 0))
                payment_method = request.POST.get('payment_method', 'CASH')
                transaction_reference = request.POST.get('transaction_reference', '')
                notes = request.POST.get('notes', '')

                # Validate amount
                if payment_amount <= 0:
                    raise ValueError("Payment amount must be greater than zero")

                if payment_amount > invoice.amount_outstanding:
                    raise ValueError(
                        f"Payment amount ({payment_amount}) exceeds outstanding amount "
                        f"({invoice.amount_outstanding})"
                    )

                # Allocate payment
                payment = invoice.allocate_payment(
                    payment_amount=payment_amount,
                    payment_method=payment_method,
                    transaction_reference=transaction_reference,
                    processed_by=request.user,
                    notes=notes
                )

                messages.success(
                    request,
                    f'Payment of {invoice.currency_code} {payment_amount:,.2f} recorded successfully'
                )

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': 'Payment recorded',
                        'new_payment_status': invoice.sale.payment_status,
                        'amount_outstanding': float(invoice.amount_outstanding),
                        'payment_completion': float(invoice.payment_completion_percentage),
                        'redirect_url': reverse('invoices:detail', args=[invoice.pk])
                    })

                return redirect('invoices:detail', pk=invoice.pk)

        except Exception as e:
            logger.error(f"Error recording payment: {e}", exc_info=True)

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

            messages.error(request, f"Error recording payment: {str(e)}")

    return redirect('invoices:detail', pk=invoice.pk)


@login_required
@permission_required('invoices.change_invoice', raise_exception=True)
def create_payment_schedule(request, pk):
    """Create or update payment schedule for invoice"""

    stores = get_user_accessible_stores(request.user)

    invoice = get_object_or_404(
        get_tenant_invoices_queryset(request, base_filters=Q(store__in=stores)),
        pk=pk
    )

    try:
        validate_store_access(request.user, invoice.store, 'edit', raise_exception=True)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('invoices:detail', pk=pk)

    if request.method == 'POST':
        try:
            installments = int(request.POST.get('installments', 1))
            first_due_date = request.POST.get('first_due_date')

            if installments < 1:
                raise ValueError("Number of installments must be at least 1")

            if first_due_date:
                first_due_date = datetime.strptime(first_due_date, '%Y-%m-%d').date()
            else:
                first_due_date = invoice.due_date

            with transaction.atomic():
                invoice.create_payment_schedule(
                    installments=installments,
                    first_due_date=first_due_date
                )

            messages.success(
                request,
                f'Payment schedule created with {installments} installments'
            )

        except Exception as e:
            logger.error(f"Error creating payment schedule: {e}", exc_info=True)
            messages.error(request, f"Error creating payment schedule: {str(e)}")

    return redirect('invoices:detail', pk=pk)


# ============================================================================
# PAYMENT REMINDER VIEWS
# ============================================================================

@login_required
@permission_required('invoices.change_invoice', raise_exception=True)
def send_reminder(request, pk):
    """Send payment reminder for invoice"""

    stores = get_user_accessible_stores(request.user)

    invoice = get_object_or_404(
        get_tenant_invoices_queryset(request, base_filters=Q(store__in=stores)),
        pk=pk
    )

    try:
        validate_store_access(request.user, invoice.store, 'edit', raise_exception=True)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('invoices:detail', pk=pk)

    if request.method == 'POST':
        try:
            from .reminder_service import PaymentReminderService

            reminder_type = request.POST.get('reminder_type', 'DUE')
            method = request.POST.get('method', 'EMAIL')
            payment_schedule_id = request.POST.get('payment_schedule_id')

            payment_schedule = None
            if payment_schedule_id:
                payment_schedule = PaymentSchedule.objects.get(
                    id=payment_schedule_id,
                    invoice=invoice
                )

            reminder = PaymentReminderService.send_reminder(
                invoice=invoice,
                reminder_type=reminder_type,
                payment_schedule=payment_schedule,
                method=method
            )

            if reminder and reminder.is_successful:
                messages.success(request, f'Payment reminder sent successfully via {method}')
            else:
                error_msg = reminder.error_message if reminder else 'Unknown error'
                messages.error(request, f'Failed to send reminder: {error_msg}')

        except Exception as e:
            logger.error(f"Error sending reminder: {e}", exc_info=True)
            messages.error(request, f"Error sending reminder: {str(e)}")

    return redirect('invoices:detail', pk=pk)


@login_required
@permission_required('invoices.view_invoice', raise_exception=True)
def payment_reminders_list(request):
    """List all payment reminders"""

    stores = get_user_accessible_stores(request.user)

    reminders = PaymentReminder.objects.filter(
        invoice__store__in=stores
    ).select_related(
        'invoice__sale__customer',
        'payment_schedule',
        'sent_by'
    ).order_by('-sent_at')

    # Filters
    reminder_type = request.GET.get('reminder_type')
    if reminder_type:
        reminders = reminders.filter(reminder_type=reminder_type)

    status_filter = request.GET.get('status')
    if status_filter == 'successful':
        reminders = reminders.filter(is_successful=True)
    elif status_filter == 'failed':
        reminders = reminders.filter(is_successful=False)

    # Pagination
    paginator = Paginator(reminders, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Statistics
    stats = {
        'total_reminders': reminders.count(),
        'successful': reminders.filter(is_successful=True).count(),
        'failed': reminders.filter(is_successful=False).count(),
        'today': reminders.filter(sent_at__date=timezone.now().date()).count(),
    }

    context = {
        'page_obj': page_obj,
        'reminders': page_obj.object_list,
        'stats': stats,
        'reminder_type': reminder_type,
        'status_filter': status_filter,
    }

    return render(request, 'invoices/reminders_payment.html')