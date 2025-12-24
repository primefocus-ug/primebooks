from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.urls import reverse_lazy, reverse
from django.db.models import Q, Sum, Count, F, Avg, ExpressionWrapper, DurationField
from django.utils import timezone
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
import json
import logging
from django_tenants.utils import tenant_context
import csv
from django.core.exceptions import ValidationError
from datetime import timedelta, datetime
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from efris.models import FiscalizationAudit
from sales.models import Sale
from .models import Invoice, InvoiceTemplate, InvoicePayment
from .forms import (
    InvoiceForm, InvoiceSearchForm, InvoicePaymentForm,
    InvoiceTemplateForm, BulkInvoiceActionForm, FiscalizationForm
)

logger = logging.getLogger(__name__)


def get_current_tenant(request):
    """Get current tenant from request"""
    return getattr(request, 'tenant', None)


def get_user_company(user):
    """Get user's company"""
    return getattr(user, 'company', None)


class InvoiceListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Invoice
    template_name = 'invoices/invoice_list.html'
    context_object_name = 'invoices'
    paginate_by = 20
    permission_required = 'invoices.view_invoice'

    def get_queryset(self):
        company = get_current_tenant(self.request)
        if not company:
            return Invoice.objects.none()

        with tenant_context(company):
            queryset = Invoice.objects.filter(
                sale__store__company=company,
                sale__document_type='INVOICE'  # Only show invoices
            ).select_related(
                'sale', 'sale__customer', 'sale__store',
                'created_by', 'fiscalized_by'
            ).prefetch_related('payments')

            # Apply search filters
            form = InvoiceSearchForm(self.request.GET)
            if form.is_valid():
                search = form.cleaned_data.get('search')
                if search:
                    queryset = queryset.filter(
                        Q(sale__document_number__icontains=search) |
                        Q(fiscal_document_number__icontains=search) |
                        Q(sale__customer__name__icontains=search)
                    )

                # ✅ FIX: Correct status filtering
                status = form.cleaned_data.get('status')
                if status:
                    queryset = queryset.filter(
                        Q(sale__status=status) | Q(sale__payment_status=status)
                    )

                document_type = form.cleaned_data.get('document_type')
                if document_type:
                    queryset = queryset.filter(sale__document_type=document_type)

                date_from = form.cleaned_data.get('date_from')
                if date_from:
                    queryset = queryset.filter(sale__created_at__date__gte=date_from)

                date_to = form.cleaned_data.get('date_to')
                if date_to:
                    queryset = queryset.filter(sale__created_at__date__lte=date_to)

                amount_min = form.cleaned_data.get('amount_min')
                if amount_min:
                    queryset = queryset.filter(sale__total_amount__gte=amount_min)

                amount_max = form.cleaned_data.get('amount_max')
                if amount_max:
                    queryset = queryset.filter(sale__total_amount__lte=amount_max)

                if form.cleaned_data.get('is_overdue'):
                    queryset = queryset.filter(
                        sale__due_date__lt=timezone.now().date(),
                        sale__payment_status__in=['PENDING', 'PARTIALLY_PAID']
                    )

                if form.cleaned_data.get('is_fiscalized'):
                    queryset = queryset.filter(is_fiscalized=True)

                # ✅ FIX: Filter by payment method through sale
                payment_method = form.cleaned_data.get('payment_method')
                if payment_method:
                    queryset = queryset.filter(sale__payment_method=payment_method)

                # ✅ FIX: Filter by credit status through sale
                credit_status = form.cleaned_data.get('credit_status')
                if credit_status:
                    if credit_status == 'CREDIT_ONLY':
                        queryset = queryset.filter(sale__payment_method='CREDIT')
                    elif credit_status == 'OVERDUE_CREDIT':
                        queryset = queryset.filter(
                            sale__payment_method='CREDIT',
                            sale__payment_status='OVERDUE'
                        )
                    elif credit_status == 'OUTSTANDING_CREDIT':
                        queryset = queryset.filter(
                            sale__payment_method='CREDIT',
                            sale__payment_status__in=['PENDING', 'PARTIALLY_PAID']
                        )
                    elif credit_status == 'PAID_CREDIT':
                        queryset = queryset.filter(
                            sale__payment_method='CREDIT',
                            sale__payment_status='PAID'
                        )

            return queryset.order_by('-sale__created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = InvoiceSearchForm(self.request.GET)

        # Get the filtered queryset
        queryset = self.get_queryset()

        # ✅ FIX: Access payment_method through sale
        credit_invoices = queryset.filter(sale__payment_method='CREDIT')
        cash_invoices = queryset.filter(sale__payment_method__in=['CASH', 'CARD', 'BANK_TRANSFER'])

        # Calculate overdue days for overdue credit invoices
        overdue_credit_invoices = credit_invoices.filter(
            sale__payment_status='OVERDUE'
        ).select_related('sale')

        overdue_details = []
        for invoice in overdue_credit_invoices:
            if invoice.sale.due_date:
                overdue_days = (timezone.now().date() - invoice.sale.due_date).days
                overdue_details.append({
                    'invoice_no': invoice.sale.document_number,
                    'customer': invoice.sale.customer.name if invoice.sale.customer else 'N/A',
                    'amount': invoice.sale.total_amount,
                    'due_date': invoice.sale.due_date,
                    'overdue_days': overdue_days,
                    'contact': invoice.sale.customer.phone if invoice.sale.customer else ''
                })

        context['credit_stats'] = {
            'total_credit_invoices': credit_invoices.count(),
            'total_credit_amount': credit_invoices.aggregate(
                Sum('sale__total_amount')
            )['sale__total_amount__sum'] or 0,
            'overdue_credit': credit_invoices.filter(
                sale__payment_status='OVERDUE'
            ).count(),
            'overdue_credit_amount': credit_invoices.filter(
                sale__payment_status='OVERDUE'
            ).aggregate(Sum('sale__total_amount'))['sale__total_amount__sum'] or 0,
            'pending_credit': credit_invoices.filter(
                sale__payment_status__in=['PENDING', 'PARTIALLY_PAID']
            ).count(),
            'paid_credit': credit_invoices.filter(
                sale__payment_status='PAID'
            ).count(),
            'overdue_details': overdue_details[:5],
            'cash_invoices_count': cash_invoices.count(),
            'cash_invoices_amount': cash_invoices.aggregate(
                Sum('sale__total_amount')
            )['sale__total_amount__sum'] or 0,
            'credit_vs_cash_ratio': (
                (credit_invoices.count() / max(queryset.count(), 1) * 100)
                if queryset.count() > 0 else 0
            ),
        }

        # ✅ FIX: Access customer through sale
        top_credit_customers = credit_invoices.values(
            'sale__customer__id', 'sale__customer__name', 'sale__customer__phone'
        ).annotate(
            invoice_count=Count('id'),
            total_credit=Sum('sale__total_amount'),
            overdue_count=Count('id', filter=Q(sale__payment_status='OVERDUE'))
        ).order_by('-total_credit')[:5]

        context['top_credit_customers'] = top_credit_customers

        # ✅ FIX: Payment status breakdown through sale
        credit_payment_stats = credit_invoices.values(
            'sale__payment_status'
        ).annotate(
            count=Count('id'),
            total=Sum('sale__total_amount')
        ).order_by('sale__payment_status')

        context['credit_payment_stats'] = [
            {
                'status': stat['sale__payment_status'],
                'status_display': dict(Sale.PAYMENT_STATUS_CHOICES).get(
                    stat['sale__payment_status'],
                    stat['sale__payment_status']
                ),
                'count': stat['count'],
                'total': stat['total'] or 0,
                'percentage': (stat['count'] / max(credit_invoices.count(), 1) * 100)
            }
            for stat in credit_payment_stats
        ]

        return context


@login_required
@permission_required('invoices.change_invoice')
def cancel_invoice(request, pk):
    """Cancel/void an invoice"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('invoices:list')

    with tenant_context(company):
        invoice = get_object_or_404(
            Invoice.objects.filter(sale__store__company=company),
            pk=pk
        )

        if request.method == 'POST':
            reason = request.POST.get('reason', '')
            if not reason:
                messages.error(request, 'Please provide a cancellation reason')
                return redirect('invoices:detail', pk=invoice.pk)

            try:
                success = invoice.cancel_invoice(reason, request.user)
                if success:
                    messages.success(request, 'Invoice cancelled successfully')
                else:
                    messages.error(request, 'Failed to cancel invoice')
            except ValidationError as e:
                messages.error(request, str(e))
            except Exception as e:
                logger.error(f"Error cancelling invoice {invoice.id}: {e}")
                messages.error(request, 'An error occurred while cancelling the invoice')

            return redirect('invoices:detail', pk=invoice.pk)

        # GET request - show confirmation modal
        return render(request, 'invoices/partials/cancel_modal.html', {'invoice': invoice})


@login_required
@permission_required('invoices.change_invoice')
def mark_as_paid(request, pk):
    """Mark invoice as fully paid"""
    company = get_current_tenant(request)
    if not company:
        return JsonResponse({'success': False, 'error': 'No company context'})

    with tenant_context(company):
        invoice = get_object_or_404(
            Invoice.objects.filter(sale__store__company=company),
            pk=pk
        )

        if request.method == 'POST':
            try:
                # Use JSON for AJAX requests
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    data = json.loads(request.body) if request.body else {}
                    confirm = data.get('confirm', False)
                else:
                    confirm = request.POST.get('confirm', False)

                if not confirm:
                    return JsonResponse({
                        'success': False,
                        'error': 'Confirmation required'
                    })

                with transaction.atomic():
                    # Get payment method from request or default to cash
                    payment_method = 'CASH'
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        data = json.loads(request.body) if request.body else {}
                        payment_method = data.get('payment_method', 'CASH')
                    else:
                        payment_method = request.POST.get('payment_method', 'CASH')

                    # ✅ DEBUG: Log before payment
                    logger.info(
                        f"BEFORE PAYMENT - Invoice {invoice.id}: "
                        f"Total: {invoice.sale.total_amount}, "
                        f"Paid: {invoice.amount_paid}, "
                        f"Outstanding: {invoice.amount_outstanding}, "
                        f"Status: {invoice.sale.payment_status}"
                    )

                    # Create payment for full outstanding amount
                    outstanding = invoice.amount_outstanding
                    if outstanding > 0:
                        payment, allocations, remaining = invoice.apply_payment(
                            amount=outstanding,
                            payment_method=payment_method,
                            user=request.user,
                            transaction_ref=f"MANUAL-PAY-{invoice.invoice_number}",
                            notes='Marked as fully paid'
                        )

                        # Force refresh
                        invoice.refresh_from_db()
                        invoice.sale.refresh_from_db()

                        # Force status update
                        invoice.update_payment_status(commit=True)

                        # Refresh again
                        invoice.refresh_from_db()
                        invoice.sale.refresh_from_db()

                    # ✅ DEBUG: Log after payment
                    logger.info(
                        f"AFTER PAYMENT - Invoice {invoice.id}: "
                        f"Total: {invoice.sale.total_amount}, "
                        f"Paid: {invoice.amount_paid}, "
                        f"Outstanding: {invoice.amount_outstanding}, "
                        f"Status: {invoice.sale.payment_status}"
                    )

                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({
                            'success': True,
                            'message': f'Invoice marked as paid successfully. Status: {invoice.sale.get_payment_status_display()}',
                            'new_status': invoice.sale.payment_status,
                            'amount_paid': float(invoice.amount_paid),
                            'amount_outstanding': float(invoice.amount_outstanding)
                        })
                    else:
                        messages.success(request, 'Invoice marked as paid successfully')
                        return redirect('invoices:detail', pk=invoice.pk)

            except Exception as e:
                logger.error(f"Error marking invoice {invoice.id} as paid: {e}", exc_info=True)
                error_msg = f'An error occurred: {str(e)}'

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': error_msg
                    })
                else:
                    messages.error(request, error_msg)
                    return redirect('invoices:detail', pk=invoice.pk)

        # GET request - show confirmation
        return render(request, 'invoices/partials/mark_paid_modal.html', {'invoice': invoice})


@login_required
@permission_required('invoices.view_invoicepayment')
def payment_reconciliation(request):
    """View to reconcile payments"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('invoices:list')

    with tenant_context(company):
        # Get payments that need reconciliation
        payments = InvoicePayment.objects.filter(
            invoice__sale__store__company=company
        ).select_related(
            'invoice', 'invoice__sale', 'processed_by'
        ).order_by('-payment_date')

        # Get summary
        summary = {
            'total_payments': payments.count(),
            'total_amount': payments.aggregate(Sum('amount'))['amount__sum'] or 0,
            'allocated_payments': payments.filter(is_allocated=True).count(),
            'unallocated_payments': payments.filter(is_allocated=False).count(),
            'unallocated_amount': payments.filter(is_allocated=False).aggregate(
                Sum('amount')
            )['amount__sum'] or 0,
        }

        context = {
            'payments': payments,
            'summary': summary,
        }

        return render(request, 'invoices/payment_reconciliation.html', context)


@login_required
@permission_required('invoices.change_invoicepayment')
def allocate_payment(request, payment_id):
    """Manually allocate an unallocated payment"""
    company = get_current_tenant(request)
    if not company:
        return JsonResponse({'success': False, 'error': 'No company context'})

    with tenant_context(company):
        payment = get_object_or_404(
            InvoicePayment.objects.filter(
                invoice__sale__store__company=company,
                is_allocated=False
            ),
            pk=payment_id
        )

        try:
            payment.allocate_payment()
            messages.success(request, f'Payment #{payment.id} allocated successfully')
        except Exception as e:
            messages.error(request, f'Error allocating payment: {str(e)}')

        return redirect('invoices:payment_reconciliation')


class InvoiceDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Invoice
    template_name = 'invoices/invoice_detail.html'
    context_object_name = 'invoice'
    permission_required = 'invoices.view_invoice'

    def get_queryset(self):
        company = get_current_tenant(self.request)
        if not company:
            return Invoice.objects.none()

        return Invoice.objects.filter(
            sale__store__company=company
        ).select_related(
            'sale', 'sale__customer', 'sale__store', 'sale__store__company',
            'created_by', 'fiscalized_by'
        ).prefetch_related(
            'payments__processed_by',
            'fiscalization_audits',
            'payment_schedules'  # ADD: Prefetch payment schedules
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object

        # Add sale to context for template access
        context['sale'] = invoice.sale

        context['payment_form'] = InvoicePaymentForm(invoice=invoice)
        context['fiscalization_form'] = FiscalizationForm(invoice=invoice)

        # EFRIS status
        can_fiscalize = False
        fiscalization_error = None
        efris_status = {}

        if invoice.sale and invoice.sale.store:
            company = invoice.sale.store.company
            efris_enabled = getattr(company, 'efris_enabled', False)

            if efris_enabled:
                with tenant_context(company):
                    can_fiscalize, fiscalization_error = invoice.can_fiscalize(
                        self.request.user
                    )

                    efris_status = {
                        'enabled': True,
                        'can_fiscalize': can_fiscalize,
                        'fiscalization_error': fiscalization_error,
                        'fiscal_document_number': invoice.fiscal_document_number,
                        'verification_code': invoice.verification_code,
                        'is_fiscalized': invoice.is_fiscalized,
                        'fiscalization_status': invoice.fiscalization_status,
                    }
            else:
                efris_status = {
                    'enabled': False,
                    'reason': 'EFRIS not enabled for this company'
                }

        # ADD: Customer credit information for credit invoices
        customer_credit_info = None
        customer = None  # Initialize customer variable
        if invoice.sale.customer and invoice.sale.payment_method == 'CREDIT':
            customer = invoice.sale.customer
            customer.update_credit_balance()

            # Get other outstanding invoices for this customer
            other_outstanding = Invoice.objects.filter(
                sale__customer=customer,
                sale__document_type='INVOICE',
                sale__payment_method='CREDIT',
                sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
            ).exclude(id=invoice.id).select_related('sale')

            # Calculate total outstanding including this invoice
            all_outstanding = other_outstanding | Invoice.objects.filter(id=invoice.id)
            total_outstanding_amount = all_outstanding.aggregate(
                Sum('sale__total_amount')
            )['sale__total_amount__sum'] or 0

            # Calculate remaining credit
            remaining_credit = max(Decimal('0'), customer.credit_limit - customer.credit_balance)

            customer_credit_info = {
                'allow_credit': customer.allow_credit,
                'credit_limit': customer.credit_limit,
                'credit_balance': customer.credit_balance,
                'credit_available': customer.credit_available,
                'credit_status': customer.credit_status,
                'credit_status_display': customer.get_credit_status_display(),
                'has_overdue': customer.has_overdue_invoices,
                'overdue_amount': customer.overdue_amount,
                'other_outstanding_count': other_outstanding.count(),
                'other_outstanding_amount': other_outstanding.aggregate(
                    Sum('sale__total_amount')
                )['sale__total_amount__sum'] or 0,
                'total_outstanding_amount': total_outstanding_amount,
                'remaining_credit': remaining_credit,
                'credit_days': customer.credit_days,
                'credit_utilization_percentage': (
                    (customer.credit_balance / customer.credit_limit * 100)
                    if customer.credit_limit > 0 else 0
                ),
            }

        # ADD: Payment schedule info for credit invoices
        payment_schedules = []
        next_payment_due = None
        payment_schedule_summary = {}
        if invoice.sale.payment_method == 'CREDIT':
            payment_schedules = invoice.payment_schedules.all().order_by('due_date')
            next_payment_due = invoice.get_next_schedule_due()

            # Calculate payment schedule summary
            if payment_schedules.exists():
                total_scheduled = payment_schedules.aggregate(
                    total=Sum('amount')
                )['total'] or Decimal('0')
                total_paid_scheduled = payment_schedules.filter(
                    is_paid=True
                ).aggregate(
                    total=Sum('amount')
                )['total'] or Decimal('0')
                overdue_schedules = payment_schedules.filter(
                    due_date__lt=timezone.now().date(),
                    is_paid=False
                )

                payment_schedule_summary = {
                    'total_scheduled': total_scheduled,
                    'total_paid_scheduled': total_paid_scheduled,
                    'remaining_scheduled': total_scheduled - total_paid_scheduled,
                    'overdue_schedules_count': overdue_schedules.count(),
                    'overdue_schedules_amount': overdue_schedules.aggregate(
                        total=Sum('amount')
                    )['total'] or Decimal('0'),
                    'completed_percentage': (
                        (total_paid_scheduled / total_scheduled * 100)
                        if total_scheduled > 0 else 0
                    ),
                }

        # Calculate credit terms - FIXED: Use safe access to customer
        if invoice.sale.customer and invoice.sale.customer.credit_days:
            credit_terms = f"Net {invoice.sale.customer.credit_days} days"
        else:
            credit_terms = "Net 30 days"

        context.update({
            'can_fiscalize': can_fiscalize,
            'fiscalize_message': fiscalization_error,
            'efris_status': efris_status,
            'fiscalization_history': invoice.fiscalization_audits.order_by(
                '-timestamp'
            )[:10],
            'customer_credit_info': customer_credit_info,
            'payment_schedules': payment_schedules,
            'payment_schedule_summary': payment_schedule_summary,
            'next_payment_due': next_payment_due,
            'is_credit_invoice': invoice.sale.payment_method == 'CREDIT',
            'is_cash_invoice': invoice.sale.payment_method != 'CREDIT',
            'requires_due_date': invoice.sale.payment_method == 'CREDIT',
            'overdue_days': (
                (timezone.now().date() - invoice.sale.due_date).days
                if invoice.sale.due_date and invoice.sale.due_date < timezone.now().date()
                else 0
            ),
            'credit_terms': credit_terms,  # Use the calculated credit_terms variable
        })

        return context

@login_required
@permission_required('invoices.view_invoice')
def customer_credit_dashboard(request):
    """Dashboard showing customer credit status and outstanding invoices"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('invoices:list')

    with tenant_context(company):
        from customers.models import Customer
        from sales.models import Sale  # Import Sale model

        # Get customers with credit enabled
        credit_customers = Customer.objects.filter(
            allow_credit=True,
            is_active=True
        ).annotate(
            total_outstanding=Sum(
                'sale__total_amount',  # Changed from 'sales__' to 'sale__' based on Customer model
                filter=Q(
                    sale__document_type='INVOICE',
                    sale__payment_method='CREDIT',
                    sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
                )
            ),
            overdue_amount=Sum(
                'sale__total_amount',
                filter=Q(
                    sale__document_type='INVOICE',
                    sale__payment_method='CREDIT',
                    sale__payment_status='OVERDUE'
                )
            ),
            invoice_count=Count(
                'sale',
                filter=Q(
                    sale__document_type='INVOICE',
                    sale__payment_method='CREDIT',
                    sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
                )
            )
        ).order_by('-total_outstanding')

        # Update credit balances
        for customer in credit_customers:
            customer.update_credit_balance()

        # Calculate summary statistics
        total_credit_limit = credit_customers.aggregate(
            Sum('credit_limit')
        )['credit_limit__sum'] or 0

        total_credit_used = credit_customers.aggregate(
            Sum('credit_balance')
        )['credit_balance__sum'] or 0

        total_credit_available = credit_customers.aggregate(
            Sum('credit_available')
        )['credit_available__sum'] or 0

        customers_at_limit = credit_customers.filter(
            credit_balance__gte=F('credit_limit') * 0.9
        ).count()

        customers_overdue = credit_customers.filter(
            credit_status__in=['WARNING', 'SUSPENDED', 'BLOCKED']
        ).count()

        # Credit status distribution
        status_distribution = credit_customers.values('credit_status').annotate(
            count=Count('id'),
            total_outstanding=Sum('credit_balance')
        )

        context = {
            'credit_customers': credit_customers[:50],  # Top 50
            'total_credit_limit': total_credit_limit,
            'total_credit_used': total_credit_used,
            'total_credit_available': total_credit_available,
            'customers_at_limit': customers_at_limit,
            'customers_overdue': customers_overdue,
            'credit_utilization': (total_credit_used / total_credit_limit * 100) if total_credit_limit > 0 else 0,
            'status_distribution': status_distribution,
        }

        return render(request, 'invoices/customer_credit_dashboard.html', context)


@login_required
@permission_required('invoices.view_invoice')
def customer_credit_detail(request, customer_id):
    """Detailed view of customer's credit account"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('invoices:list')

    with tenant_context(company):
        from customers.models import Customer, CustomerCreditStatement

        customer = get_object_or_404(Customer, id=customer_id)

        # Update credit balance
        customer.update_credit_balance()

        # Get outstanding invoices
        outstanding_invoices = Invoice.objects.filter(
            sale__customer=customer,
            sale__document_type='INVOICE',
            sale__payment_method='CREDIT',
            sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
        ).select_related('sale').order_by('sale__due_date')

        # Get payment history
        recent_payments = InvoicePayment.objects.filter(
            invoice__sale__customer=customer
        ).select_related('invoice__sale').order_by('-payment_date')[:20]

        # Get credit statement
        credit_statements = customer.credit_statements.order_by('-created_at')[:50]

        # Calculate aging buckets
        today = timezone.now().date()
        aging_buckets = {
            'current': Decimal('0'),  # Not yet due
            '1-30': Decimal('0'),  # 1-30 days overdue
            '31-60': Decimal('0'),  # 31-60 days overdue
            '61-90': Decimal('0'),  # 61-90 days overdue
            '90+': Decimal('0'),  # 90+ days overdue
        }

        for invoice in outstanding_invoices:
            outstanding = invoice.amount_outstanding
            if not invoice.due_date or invoice.due_date >= today:
                aging_buckets['current'] += outstanding
            else:
                days_overdue = (today - invoice.due_date).days
                if days_overdue <= 30:
                    aging_buckets['1-30'] += outstanding
                elif days_overdue <= 60:
                    aging_buckets['31-60'] += outstanding
                elif days_overdue <= 90:
                    aging_buckets['61-90'] += outstanding
                else:
                    aging_buckets['90+'] += outstanding

        context = {
            'customer': customer,
            'outstanding_invoices': outstanding_invoices,
            'recent_payments': recent_payments,
            'credit_statements': credit_statements,
            'aging_buckets': aging_buckets,
            'credit_info': {
                'limit': customer.credit_limit,
                'balance': customer.credit_balance,
                'available': customer.credit_available,
                'status': customer.credit_status,
                'status_display': customer.get_credit_status_display(),
                'utilization': (
                            customer.credit_balance / customer.credit_limit * 100) if customer.credit_limit > 0 else 0,
            }
        }

        return render(request, 'invoices/customer_credit_detail.html', context)


@login_required
@permission_required('invoices.view_invoice')
def export_invoice_pdf(request, pk):
    """Export single invoice to PDF"""
    company = get_current_tenant(request)
    if not company:
        return HttpResponse('No company context', status=403)

    with tenant_context(company):
        invoice = get_object_or_404(
            Invoice.objects.filter(sale__store__company=company),
            pk=pk
        )

        # Create PDF response
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="invoice_{invoice.invoice_number}.pdf"'

        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from io import BytesIO

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []

        # Styles
        styles = getSampleStyleSheet()

        # Header
        elements.append(Paragraph(f"Invoice #{invoice.invoice_number}", styles['Heading1']))
        elements.append(Spacer(1, 12))

        # Company and Customer Info
        company_data = [
            ['From:', f'{company.name}', 'To:', f'{invoice.customer.name if invoice.customer else "Walk-in Customer"}'],
            ['Address:', f'{company.physical_address or ""}', 'Address:',
             f'{invoice.customer.physical_address if invoice.customer and invoice.customer.physical_address else ""}'],
            ['Phone:', f'{company.phone or ""}', 'Phone:',
             f'{invoice.customer.phone if invoice.customer and invoice.customer.phone else ""}'],
            ['Email:', f'{company.email or ""}', 'Email:',
             f'{invoice.customer.email if invoice.customer and invoice.customer.email else ""}'],
            ['TIN:', f'{company.tin or ""}', 'TIN:',
             f'{invoice.customer.tin if invoice.customer and invoice.customer.tin else ""}'],
        ]

        company_table = Table(company_data, colWidths=[1 * inch, 2 * inch, 1 * inch, 2 * inch])
        company_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(company_table)
        elements.append(Spacer(1, 20))

        # Invoice Details
        details_data = [
            ['Invoice Date:', invoice.issue_date.strftime('%B %d, %Y') if invoice.issue_date else 'N/A'],
            ['Due Date:', invoice.due_date.strftime('%B %d, %Y') if invoice.due_date else 'N/A'],
            ['Status:', invoice.sale.get_payment_status_display()],
            ['Payment Method:', invoice.sale.get_payment_method_display()],
        ]

        if invoice.is_fiscalized and invoice.fiscal_document_number:
            details_data.append(['Fiscal No:', invoice.fiscal_document_number])
            details_data.append(['Verification Code:', invoice.verification_code or 'N/A'])

        details_table = Table(details_data, colWidths=[1.5 * inch, 3 * inch])
        details_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 20))

        # Items Table
        items_header = ['Item', 'Quantity', 'Unit Price', 'Total']
        items_data = [items_header]

        for item in invoice.sale.items.all():
            item_name = item.product.name if item.product else item.service.name if item.service else item.description
            items_data.append([
                item_name,
                str(item.quantity),
                f"{item.unit_price:,.2f}",
                f"{item.total_price:,.2f}"
            ])

        items_table = Table(items_data, colWidths=[3 * inch, 1 * inch, 1.5 * inch, 1.5 * inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 20))

        # Totals
        totals_data = [
            ['Subtotal:', f"{invoice.subtotal:,.2f}"],
            ['Tax:', f"{invoice.tax_amount:,.2f}"],
        ]

        if invoice.discount_amount and invoice.discount_amount > 0:
            totals_data.append(['Discount:', f"-{invoice.discount_amount:,.2f}"])

        totals_data.append(['Total Amount:', f"{invoice.total_amount:,.2f}"])
        totals_data.append(['Amount Paid:', f"{invoice.amount_paid:,.2f}"])
        totals_data.append(['Balance Due:', f"{invoice.amount_outstanding:,.2f}"])

        totals_table = Table(totals_data, colWidths=[2 * inch, 1.5 * inch])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -2), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -2), 11),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(totals_table)

        # Notes
        if invoice.sale.notes:
            elements.append(Spacer(1, 20))
            elements.append(Paragraph("Notes:", styles['Heading3']))
            elements.append(Paragraph(invoice.sale.notes, styles['Normal']))

        # EFRIS Information
        if invoice.is_fiscalized:
            elements.append(Spacer(1, 20))
            elements.append(Paragraph("EFRIS Information:", styles['Heading3']))
            efris_data = [
                ['Fiscal Document Number:', invoice.fiscal_document_number],
                ['Verification Code:', invoice.verification_code or 'N/A'],
                ['Fiscalization Date:',
                 invoice.fiscalization_time.strftime('%B %d, %Y %H:%M') if invoice.fiscalization_time else 'N/A'],
            ]
            efris_table = Table(efris_data, colWidths=[2 * inch, 3 * inch])
            efris_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(efris_table)

        # Build PDF
        doc.build(elements)
        pdf_data = buffer.getvalue()
        buffer.close()
        response.write(pdf_data)

        return response


@login_required
@permission_required('invoices.change_invoice')
def send_payment_reminder(request, pk):
    """Send payment reminder to customer"""
    company = get_current_tenant(request)
    if not company:
        return JsonResponse({'success': False, 'error': 'No company context'})

    with tenant_context(company):
        invoice = get_object_or_404(
            Invoice.objects.filter(sale__store__company=company),
            pk=pk
        )

        # Check if invoice is eligible for reminder
        if invoice.sale.payment_status not in ['PENDING', 'PARTIALLY_PAID', 'OVERDUE']:
            return JsonResponse({
                'success': False,
                'error': 'Invoice is already paid'
            })

        if not invoice.sale.customer or not invoice.sale.customer.email:
            return JsonResponse({
                'success': False,
                'error': 'Customer has no email address'
            })

        try:
            # Create reminder record
            from invoices.models import PaymentReminder

            # Determine reminder type based on due date
            today = timezone.now().date()
            if invoice.due_date:
                days_diff = (invoice.due_date - today).days
                if days_diff > 3:
                    reminder_type = 'UPCOMING'
                elif days_diff >= 0:
                    reminder_type = 'DUE'
                elif days_diff > -30:
                    reminder_type = 'OVERDUE'
                else:
                    reminder_type = 'FINAL_NOTICE'
            else:
                reminder_type = 'DUE'

            reminder = PaymentReminder.objects.create(
                invoice=invoice,
                reminder_type=reminder_type,
                reminder_method='EMAIL',
                sent_by=request.user,
                recipient_email=invoice.sale.customer.email,
                subject=f'Payment Reminder: Invoice {invoice.invoice_number}',
                message=f'''
Dear {invoice.sale.customer.name},

This is a reminder regarding invoice {invoice.invoice_number}.

Invoice Amount: {invoice.total_amount:,.2f} {invoice.currency_code}
Amount Outstanding: {invoice.amount_outstanding:,.2f} {invoice.currency_code}
Due Date: {invoice.due_date}

Please arrange payment at your earliest convenience.

Thank you,
{company.name}
                '''.strip()
            )

            # Send email (implement your email logic here)
            from django.core.mail import send_mail

            try:
                send_mail(
                    reminder.subject,
                    reminder.message,
                    company.email,
                    [reminder.recipient_email],
                    fail_silently=False,
                )

                reminder.is_successful = True
                reminder.save(update_fields=['is_successful'])

                # Schedule next reminder if appropriate
                if reminder_type != 'FINAL_NOTICE':
                    reminder.next_reminder_date = today + timedelta(days=7)
                    reminder.save(update_fields=['next_reminder_date'])

                return JsonResponse({
                    'success': True,
                    'message': f'Payment reminder sent to {invoice.sale.customer.email}'
                })

            except Exception as e:
                reminder.is_successful = False
                reminder.error_message = str(e)
                reminder.save(update_fields=['is_successful', 'error_message'])

                return JsonResponse({
                    'success': False,
                    'error': f'Failed to send email: {str(e)}'
                })

        except Exception as e:
            logger.error(f"Error sending payment reminder: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            })


@login_required
@permission_required('invoices.view_invoice')
def credit_aging_report(request):
    """Accounts receivable aging report for credit invoices"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('invoices:list')

    with tenant_context(company):
        from customers.models import Customer

        today = timezone.now().date()

        # Get all credit customers with outstanding balances
        # FIXED: Changed 'sales__' to 'sale__'
        customers = Customer.objects.filter(
            allow_credit=True,
            is_active=True,
            sale__document_type='INVOICE',
            sale__payment_method='CREDIT',
            sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
        ).distinct()

        aging_data = []

        for customer in customers:
            customer.update_credit_balance()

            # Get outstanding invoices
            outstanding_invoices = Invoice.objects.filter(
                sale__customer=customer,
                sale__document_type='INVOICE',
                sale__payment_method='CREDIT',
                sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
            ).select_related('sale')

            # Calculate aging buckets
            current = Decimal('0')
            days_1_30 = Decimal('0')
            days_31_60 = Decimal('0')
            days_61_90 = Decimal('0')
            days_90_plus = Decimal('0')

            for invoice in outstanding_invoices:
                outstanding = invoice.amount_outstanding

                if not invoice.sale.due_date or invoice.sale.due_date >= today:
                    current += outstanding
                else:
                    days_overdue = (today - invoice.sale.due_date).days
                    if days_overdue <= 30:
                        days_1_30 += outstanding
                    elif days_overdue <= 60:
                        days_31_60 += outstanding
                    elif days_overdue <= 90:
                        days_61_90 += outstanding
                    else:
                        days_90_plus += outstanding

            total_outstanding = current + days_1_30 + days_31_60 + days_61_90 + days_90_plus

            if total_outstanding > 0:
                aging_data.append({
                    'customer': customer,
                    'current': current,
                    'days_1_30': days_1_30,
                    'days_31_60': days_31_60,
                    'days_61_90': days_61_90,
                    'days_90_plus': days_90_plus,
                    'total': total_outstanding,
                    'credit_limit': customer.credit_limit,
                    'credit_available': customer.credit_available,
                    'invoice_count': outstanding_invoices.count(),
                    'overdue_count': outstanding_invoices.filter(
                        sale__payment_status='OVERDUE'
                    ).count(),
                })

        # Sort by total outstanding (highest first)
        aging_data.sort(key=lambda x: x['total'], reverse=True)

        # Calculate totals
        totals = {
            'current': sum(item['current'] for item in aging_data),
            'days_1_30': sum(item['days_1_30'] for item in aging_data),
            'days_31_60': sum(item['days_31_60'] for item in aging_data),
            'days_61_90': sum(item['days_61_90'] for item in aging_data),
            'days_90_plus': sum(item['days_90_plus'] for item in aging_data),
            'total': sum(item['total'] for item in aging_data),
            'customer_count': len(aging_data),
            'invoice_count': sum(item['invoice_count'] for item in aging_data),
            'overdue_count': sum(item['overdue_count'] for item in aging_data),
        }

        context = {
            'aging_data': aging_data,
            'totals': totals,
            'report_date': today,
        }

        return render(request, 'invoices/credit_aging_report.html', context)


@login_required
@permission_required('invoices.view_invoice')
def export_credit_aging_csv(request):
    """Export credit aging report to CSV"""
    company = get_current_tenant(request)
    if not company:
        return HttpResponse('No company context', status=403)

    with tenant_context(company):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="credit_aging_report.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Customer', 'TIN', 'Phone', 'Credit Limit', 'Current', '1-30 Days',
            '31-60 Days', '61-90 Days', '90+ Days', 'Total Outstanding',
            'Credit Available', 'Status', 'Invoice Count', 'Overdue Count'
        ])

        from customers.models import Customer
        today = timezone.now().date()

        # FIXED: Changed 'sales__' to 'sale__'
        customers = Customer.objects.filter(
            allow_credit=True,
            is_active=True,
            sale__document_type='INVOICE',
            sale__payment_method='CREDIT',
            sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
        ).distinct()

        for customer in customers:
            customer.update_credit_balance()

            outstanding_invoices = Invoice.objects.filter(
                sale__customer=customer,
                sale__document_type='INVOICE',
                sale__payment_method='CREDIT',
                sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
            )

            # Calculate aging
            current = Decimal('0')
            days_1_30 = Decimal('0')
            days_31_60 = Decimal('0')
            days_61_90 = Decimal('0')
            days_90_plus = Decimal('0')

            for invoice in outstanding_invoices:
                outstanding = invoice.amount_outstanding

                if not invoice.sale.due_date or invoice.sale.due_date >= today:
                    current += outstanding
                else:
                    days_overdue = (today - invoice.sale.due_date).days
                    if days_overdue <= 30:
                        days_1_30 += outstanding
                    elif days_overdue <= 60:
                        days_31_60 += outstanding
                    elif days_overdue <= 90:
                        days_61_90 += outstanding
                    else:
                        days_90_plus += outstanding

            total = current + days_1_30 + days_31_60 + days_61_90 + days_90_plus

            if total > 0:
                overdue_count = outstanding_invoices.filter(
                    sale__payment_status='OVERDUE'
                ).count()

                writer.writerow([
                    customer.name or '',
                    customer.tin or '',
                    customer.phone or '',
                    customer.credit_limit,
                    current,
                    days_1_30,
                    days_31_60,
                    days_61_90,
                    days_90_plus,
                    total,
                    customer.credit_available,
                    customer.get_credit_status_display(),
                    outstanding_invoices.count(),
                    overdue_count
                ])

        return response



@login_required
@permission_required('invoices.view_invoice')
def efris_status_dashboard(request):
    """EFRIS status dashboard for invoices"""
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

    # Base queryset - Use sale__created_at
    invoices = Invoice.objects.filter(
        sale__created_at__date__gte=date_from,
        sale__created_at__date__lte=date_to,
        sale__document_type='INVOICE'  # Only invoices
    ).select_related('sale__store__company')

    # EFRIS statistics
    total_invoices = invoices.count()
    fiscalized_invoices = invoices.filter(is_fiscalized=True).count()

    # FIX: Use correct status fields
    pending_fiscalization = invoices.filter(
        fiscalization_status='pending',
        sale__status__in=['COMPLETED', 'PAID'],
        sale__payment_status__in=['PENDING', 'PAID', 'PARTIALLY_PAID']
    ).count()

    failed_fiscalization = invoices.filter(fiscalization_status='failed').count()

    # Recent activity
    recent_fiscalized = invoices.filter(
        fiscalization_time__gte=timezone.now() - timedelta(hours=24)
    ).count()

    # Company breakdown
    company_stats = invoices.values(
        'sale__store__company__name'
    ).annotate(
        total=Count('id'),
        fiscalized=Count('id', filter=Q(is_fiscalized=True)),
        pending=Count('id', filter=Q(fiscalization_status='pending')),
        failed=Count('id', filter=Q(fiscalization_status='failed'))
    ).order_by('-total')

    # Recent fiscalization activity
    recent_audits = FiscalizationAudit.objects.select_related(
        'invoice__sale', 'user'
    ).filter(
        completed_at__gte=timezone.now() - timedelta(days=7)
    ).order_by('-completed_at')[:20]

    context = {
        'date_from': date_from,
        'date_to': date_to,
        'total_invoices': total_invoices,
        'fiscalized_invoices': fiscalized_invoices,
        'pending_fiscalization': pending_fiscalization,
        'failed_fiscalization': failed_fiscalization,
        'fiscalization_rate': (fiscalized_invoices / total_invoices * 100) if total_invoices > 0 else 0,
        'recent_fiscalized': recent_fiscalized,
        'company_stats': company_stats,
        'recent_audits': recent_audits,
    }

    return render(request, 'invoices/efris_status_dashboard.html', context)


class InvoiceCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = 'invoices/invoice_form.html'
    permission_required = 'invoices.add_invoice'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        sale_id = self.request.GET.get('sale')

        if sale_id:
            company = get_current_tenant(self.request)
            if company:
                with tenant_context(company):
                    try:
                        sale = Sale.objects.get(
                            id=sale_id,
                            store__company=company
                        )
                        initial['sale'] = sale
                    except Sale.DoesNotExist:
                        pass

        return initial

    def form_valid(self, form):
        company = get_current_tenant(self.request)
        if not company:
            messages.error(self.request, 'No company context found')
            return redirect('invoices:list')

        with tenant_context(company):
            sale = form.cleaned_data['sale']

            # Check if sale is already an invoice
            if sale.document_type == 'INVOICE':
                messages.error(self.request, 'This sale is already an invoice')
                return self.form_invalid(form)

            # Use the proper conversion method if it's a proforma/estimate
            if sale.document_type in ['PROFORMA', 'ESTIMATE']:
                try:
                    # Convert using sale's method
                    converted_sale = sale.convert_to_invoice(
                        due_date=form.cleaned_data.get('due_date'),
                        terms=form.cleaned_data.get('terms')
                    )
                    sale = converted_sale  # Use the new sale
                except ValidationError as e:
                    messages.error(self.request, f'Conversion failed: {e}')
                    return self.form_invalid(form)
            else:
                # For receipts, create a new invoice sale
                from sales.models import Sale as SaleModel
                sale = SaleModel.objects.create(
                    store=sale.store,
                    created_by=self.request.user,
                    customer=sale.customer,
                    document_type='INVOICE',
                    payment_method='CREDIT',
                    due_date=form.cleaned_data.get('due_date'),
                    subtotal=sale.subtotal,
                    tax_amount=sale.tax_amount,
                    discount_amount=sale.discount_amount,
                    total_amount=sale.total_amount,
                    currency=sale.currency,
                    notes=f"Created from {sale.document_type.lower()} #{sale.document_number}",
                    duplicated_from=sale
                )

            # Now create invoice detail
            form.instance.sale = sale
            form.instance.created_by = self.request.user
            response = super().form_valid(form)

            messages.success(
                self.request,
                f'Invoice created from sale {sale.document_number}.'
            )

            return response

    def get_success_url(self):
        return reverse('invoices:detail', kwargs={'pk': self.object.pk})


class InvoiceUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """Update existing invoice"""
    model = Invoice
    form_class = InvoiceForm
    template_name = 'invoices/invoice_form.html'
    permission_required = 'invoices.change_invoice'

    def get_queryset(self):
        company = get_current_tenant(self.request)
        if not company:
            return Invoice.objects.none()

        return Invoice.objects.filter(
            sale__store__company=company
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        if self.object.is_fiscalized:
            messages.error(
                self.request,
                'Cannot edit fiscalized invoices.'
            )
            return redirect('invoices:detail', pk=self.object.pk)

        response = super().form_valid(form)
        messages.success(
            self.request,
            f'Invoice updated successfully.'
        )
        return response

    def get_success_url(self):
        return reverse('invoices:detail', kwargs={'pk': self.object.pk})


@login_required
@permission_required('invoices.add_invoicepayment')
def add_payment(request, pk):
    """Add payment to invoice"""
    company = get_current_tenant(request)
    if not company:
        return JsonResponse({'success': False, 'error': 'No company context'})

    with tenant_context(company):
        invoice = get_object_or_404(
            Invoice.objects.filter(sale__store__company=company),
            pk=pk
        )

        if request.method == 'POST':
            form = InvoicePaymentForm(request.POST, invoice=invoice)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        # Use invoice's apply_payment method
                        payment, allocations, remaining = invoice.apply_payment(
                            amount=form.cleaned_data['amount'],
                            payment_method=form.cleaned_data['payment_method'],
                            user=request.user,
                            transaction_ref=form.cleaned_data.get('transaction_reference'),
                            notes=form.cleaned_data.get('notes', '')
                        )

                        # ✅ FIX: Force refresh and update status
                        invoice.refresh_from_db()
                        invoice.sale.refresh_from_db()

                        # Double-check status update
                        invoice.update_payment_status(commit=True)

                        # Refresh again to get final status
                        invoice.refresh_from_db()
                        invoice.sale.refresh_from_db()

                        success_message = f'Payment of {payment.amount:,.2f} recorded successfully.'
                        if remaining > 0:
                            success_message += f' Note: {remaining:,.2f} remains unallocated.'

                        # Add status info to message
                        success_message += f' Payment Status: {invoice.sale.get_payment_status_display()}'

                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({
                                'success': True,
                                'message': success_message,
                                'payment_id': payment.id,
                                'new_status': invoice.sale.payment_status,
                                'amount_outstanding': float(invoice.amount_outstanding),
                                'amount_paid': float(invoice.amount_paid)
                            })

                        messages.success(request, success_message)
                        return redirect('invoices:detail', pk=invoice.pk)

                except ValidationError as e:
                    error_message = str(e)
                except Exception as e:
                    logger.error(f"Error processing payment: {e}", exc_info=True)
                    error_message = f'Error processing payment: {str(e)}'

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': error_message
                    })

                messages.error(request, error_message)
            else:
                # Form is invalid
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'errors': form.errors
                    })

                messages.error(request, 'Please correct the errors below.')

    # GET request or form errors
    return redirect('invoices:detail', pk=invoice.pk)


@login_required
@permission_required('invoices.change_invoice')
@permission_required('invoices.fiscalize_invoice')
def fiscalize_invoice(request, pk):
    """Fiscalize invoice with EFRIS"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('invoices:list')

    with tenant_context(company):
        invoice = get_object_or_404(
            Invoice.objects.filter(sale__store__company=company)
            .select_related('sale__store__company'),
            pk=pk
        )

        if request.method == 'POST':
            form = FiscalizationForm(request.POST, invoice=invoice)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        # Check if can fiscalize
                        can_fiscalize, reason = invoice.can_fiscalize(request.user)
                        if not can_fiscalize:
                            messages.error(
                                request,
                                f'Cannot fiscalize: {reason}'
                            )
                            return redirect('invoices:detail', pk=invoice.pk)

                        # Create audit record
                        audit = FiscalizationAudit.objects.create(
                            invoice=invoice,
                            action='FISCALIZE',
                            user=request.user,
                            success=False
                        )

                        try:
                            # Use EFRIS service
                            from efris.services import EFRISInvoiceService

                            service = EFRISInvoiceService(company)
                            success, message = service.fiscalize_invoice(
                                invoice,
                                request.user
                            )

                            if success:
                                audit.success = True
                                audit.fiscal_document_number = invoice.fiscal_document_number
                                audit.verification_code = invoice.verification_code
                                audit.device_number = getattr(invoice, 'device_number', '')
                                audit.save()

                                messages.success(
                                    request,
                                    f'Invoice fiscalized successfully! '
                                    f'FDN: {invoice.fiscal_document_number}'
                                )
                            else:
                                audit.error_message = message
                                audit.save()
                                messages.error(
                                    request,
                                    f'Fiscalization failed: {message}'
                                )

                        except ImportError:
                            # Fallback to basic fiscalization
                            success = invoice.fiscalize(request.user)
                            audit.success = success
                            if success:
                                audit.fiscal_document_number = invoice.fiscal_document_number
                            audit.save()

                            if success:
                                messages.success(
                                    request,
                                    'Invoice fiscalized successfully!'
                                )
                            else:
                                messages.error(
                                    request,
                                    'Fiscalization failed'
                                )

                except Exception as e:
                    logger.error(f"Fiscalization error: {e}", exc_info=True)
                    messages.error(request, f'Fiscalization failed: {str(e)}')

        return redirect('invoices:detail', pk=invoice.pk)


@login_required
@permission_required('invoices.change_invoice')
@permission_required('invoices.fiscalize_invoice')
def bulk_fiscalize_invoices(request):
    """Bulk fiscalize multiple invoices"""
    if request.method != 'POST':
        return redirect('invoices:list')

    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('invoices:list')

    with tenant_context(company):
        invoice_ids = request.POST.getlist('selected_invoices')

        if not invoice_ids:
            messages.error(request, 'No invoices selected.')
            return redirect('invoices:list')

        invoices = Invoice.objects.filter(
            id__in=invoice_ids,
            sale__store__company=company
        ).select_related('sale__store__company')

        total_processed = 0
        total_successful = 0
        total_failed = 0
        error_messages = []

        try:
            from efris.services import EFRISInvoiceService

            service = EFRISInvoiceService(company)

            for invoice in invoices:
                try:
                    can_fiscalize, reason = invoice.can_fiscalize(request.user)
                    if not can_fiscalize:
                        total_failed += 1
                        error_messages.append(
                            f"{invoice.invoice_number}: {reason}"
                        )
                        continue

                    success, message = service.fiscalize_invoice(
                        invoice,
                        request.user
                    )

                    if success:
                        total_successful += 1
                    else:
                        total_failed += 1
                        error_messages.append(
                            f"{invoice.invoice_number}: {message}"
                        )

                    total_processed += 1

                except Exception as e:
                    total_failed += 1
                    error_messages.append(
                        f"{invoice.invoice_number}: {str(e)}"
                    )

        except ImportError:
            # Fallback to individual fiscalization
            for invoice in invoices:
                try:
                    can_fiscalize, reason = invoice.can_fiscalize(request.user)
                    if can_fiscalize:
                        success = invoice.fiscalize(request.user)
                        if success:
                            total_successful += 1
                        else:
                            total_failed += 1
                    else:
                        total_failed += 1
                        error_messages.append(
                            f"{invoice.invoice_number}: {reason}"
                        )
                except Exception as e:
                    total_failed += 1
                    error_messages.append(f"{invoice.invoice_number}: {str(e)}")

                total_processed += 1

        # Report results
        if total_successful > 0:
            messages.success(
                request,
                f'Successfully fiscalized {total_successful} of {total_processed} invoices.'
            )

        if total_failed > 0:
            error_summary = f'{total_failed} invoices failed.'
            if error_messages:
                error_summary += f' First errors: {"; ".join(error_messages[:3])}'
            messages.error(request, error_summary)

    return redirect('invoices:list')


@login_required
@permission_required('invoices.change_invoice')
def bulk_actions(request):
    """Handle bulk actions on invoices"""
    if request.method != 'POST':
        return redirect('invoices:list')

    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('invoices:list')

    with tenant_context(company):
        form = BulkInvoiceActionForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data['action']
            invoice_ids = form.cleaned_data['selected_invoices']

            invoices = Invoice.objects.filter(
                id__in=invoice_ids,
                sale__store__company=company
            )
            count = invoices.count()

            if action == 'mark_sent':
                # Update related sales
                Sale.objects.filter(
                    invoice_detail__in=invoices,
                    status='DRAFT'
                ).update(status='PENDING_PAYMENT')
                messages.success(request, f'{count} invoices marked as sent.')

            elif action == 'mark_paid':
                for invoice in invoices:
                    invoice.sale.status = 'PAID'
                    invoice.sale.payment_status = 'PAID'
                    invoice.sale.save(update_fields=['status', 'payment_status'])
                messages.success(request, f'{count} invoices marked as paid.')

            elif action == 'export_pdf':
                return export_invoices_pdf(request, invoice_ids)

            elif action == 'export_csv':
                return export_invoices_csv_bulk(request, invoice_ids)

            elif action == 'fiscalize':
                return bulk_fiscalize_invoices(request)

    return redirect('invoices:list')

class PaymentListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """List all payments across invoices"""
    model = InvoicePayment
    template_name = 'invoices/payment_list.html'
    context_object_name = 'payments'
    paginate_by = 50
    permission_required = 'invoices.view_invoicepayment'

    def get_queryset(self):
        return InvoicePayment.objects.select_related(
            'invoice', 'processed_by'
        ).order_by('-payment_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Payment summary
        payments = self.get_queryset()
        context['total_payments'] = payments.count()
        context['total_amount'] = payments.aggregate(
            Sum('amount'))['amount__sum'] or 0

        # Payment methods breakdown
        context['payment_methods'] = payments.values(
            'payment_method'
        ).annotate(
            count=Count('id'),
            total=Sum('amount')
        ).order_by('-total')

        return context

@login_required
@permission_required('invoices.view_invoice')
def duplicate_invoice(request, pk):
    """Duplicate an existing invoice"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('invoices:list')

    with tenant_context(company):
        original = get_object_or_404(
            Invoice.objects.filter(sale__store__company=company),
            pk=pk
        )

        # Create duplicate invoice detail
        new_invoice = Invoice.objects.create(
            sale=original.sale,
            store=original.store,
            terms=original.terms,
            purchase_order=original.purchase_order,
            efris_document_type='4',  # Proforma
            business_type=original.business_type,
            created_by=request.user,
            fiscalization_status='pending',
            is_fiscalized=False
        )

        messages.success(
            request,
            f'Invoice duplicated successfully.'
        )

        return redirect('invoices:detail', pk=new_invoice.pk)


class FiscalizationAuditView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = FiscalizationAudit
    template_name = 'invoices/fiscalization_audit.html'
    context_object_name = 'audits'
    permission_required = 'efris.view_fiscalizationaudit'
    paginate_by = 50

    def get_queryset(self):
        queryset = FiscalizationAudit.objects.select_related(
            'invoice', 'user'
        ).order_by('-created_at')  # Changed from created_at to timestamp

        # Filter by date range
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        if date_from:
            queryset = queryset.filter(timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(timestamp__lte=date_to)

        # Filter by action type
        action = self.request.GET.get('action')
        if action:
            queryset = queryset.filter(action=action)

        # Filter by success status
        success = self.request.GET.get('success')
        if success in ['true', 'false']:
            queryset = queryset.filter(success=(success == 'true'))

        # Filter by invoice number
        invoice_number = self.request.GET.get('invoice_number')
        if invoice_number:
            queryset = queryset.filter(
                invoice__sale__document_number__icontains=invoice_number
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action_choices'] = FiscalizationAudit.ACTION_CHOICES
        # Add current filter values to context
        context['current_filters'] = {
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
            'action': self.request.GET.get('action', ''),
            'success': self.request.GET.get('success', ''),
            'invoice_number': self.request.GET.get('invoice_number', ''),
        }
        return context

@login_required
@permission_required('invoices.view_invoice')
def export_invoices_csv(request):
    """Export invoices to CSV"""
    company = get_current_tenant(request)
    if not company:
        return HttpResponse('No company context', status=403)

    with tenant_context(company):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="invoices_export.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Invoice Number', 'Document Type', 'Issue Date', 'Due Date',
            'Status', 'Customer', 'Subtotal', 'Tax', 'Discount',
            'Total', 'Paid', 'Outstanding', 'Overdue',
            'Fiscalized', 'Fiscal Number'
        ])

        invoices = Invoice.objects.filter(
            sale__store__company=company
        ).select_related('sale', 'sale__customer').order_by('-created_at')

        for invoice in invoices:
            writer.writerow([
                invoice.invoice_number,
                invoice.sale.get_document_type_display(),
                invoice.issue_date,
                invoice.due_date,
                invoice.sale.get_status_display(),
                invoice.customer.name if invoice.customer else '',
                invoice.subtotal,
                invoice.tax_amount,
                invoice.discount_amount,
                invoice.total_amount,
                invoice.amount_paid,
                invoice.amount_outstanding,
                invoice.is_overdue,
                invoice.is_fiscalized,
                invoice.fiscal_document_number or ''
            ])

        return response

def export_invoices_csv_bulk(request, invoice_ids):
    """Export selected invoices to CSV"""
    company = get_current_tenant(request)
    if not company:
        return HttpResponse('No company context', status=403)

    with tenant_context(company):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="invoices_export.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Invoice Number', 'Issue Date', 'Customer', 'Total',
            'Status', 'Fiscalized'
        ])

        invoices = Invoice.objects.filter(
            id__in=invoice_ids,
            sale__store__company=company
        ).select_related('sale', 'sale__customer')

        for invoice in invoices:
            writer.writerow([
                invoice.invoice_number,
                invoice.issue_date,
                invoice.customer.name if invoice.customer else '',
                invoice.total_amount,
                invoice.sale.get_status_display(),
                'Yes' if invoice.is_fiscalized else 'No'
            ])

        return response


def export_invoices_pdf(request, invoice_ids):
    """Export invoices to PDF"""
    company = get_current_tenant(request)
    if not company:
        return HttpResponse('No company context', status=403)

    with tenant_context(company):
        invoices = Invoice.objects.filter(
            id__in=invoice_ids,
            sale__store__company=company
        ).select_related('sale')

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="invoices_export.pdf"'

        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)

        y_position = 750
        for invoice in invoices:
            p.drawString(50, y_position, f"Invoice: {invoice.invoice_number}")
            p.drawString(50, y_position - 20, f"Amount: {invoice.total_amount:,.2f}")
            p.drawString(50, y_position - 40, f"Status: {invoice.sale.get_status_display()}")
            y_position -= 80

            if y_position < 100:
                p.showPage()
                y_position = 750

        p.save()
        pdf_data = buffer.getvalue()
        buffer.close()
        response.write(pdf_data)

        return response


class InvoiceTemplateListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """List and manage invoice templates"""
    model = InvoiceTemplate
    template_name = 'invoices/template_list.html'
    context_object_name = 'templates'
    permission_required = 'invoices.view_invoicetemplate'


class InvoiceTemplateCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """Create new invoice template"""
    model = InvoiceTemplate
    form_class = InvoiceTemplateForm
    template_name = 'invoices/template_form.html'
    success_url = reverse_lazy('invoices:templates')
    permission_required = 'invoices.add_invoicetemplate'

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)


@login_required
@permission_required('invoices.view_invoice')
def invoice_analytics(request):
    """Enhanced analytics dashboard for invoices"""
    try:
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            start_date = timezone.now().date() - timedelta(days=30)

        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            end_date = timezone.now().date()
    except (ValueError, TypeError):
        start_date = timezone.now().date() - timedelta(days=30)
        end_date = timezone.now().date()

    # Basic statistics - Use sale fields and document_type filter
    total_invoices = Invoice.objects.filter(sale__document_type='INVOICE').count()

    total_revenue = Invoice.objects.filter(
        sale__document_type='INVOICE',
        sale__payment_status='PAID'  # FIX: Use payment_status
    ).aggregate(Sum('sale__total_amount'))['sale__total_amount__sum'] or 0

    pending_amount = Invoice.objects.filter(
        sale__document_type='INVOICE'
    ).exclude(
        sale__payment_status='PAID'  # FIX: Use payment_status
    ).aggregate(Sum('sale__total_amount'))['sale__total_amount__sum'] or 0

    # FIX: Overdue invoices - use payment_status
    overdue_invoices = Invoice.objects.filter(
        sale__document_type='INVOICE',
        sale__due_date__lt=end_date,
        sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
    ).count()

    # Enhanced metrics
    invoices_this_month = Invoice.objects.filter(
        sale__document_type='INVOICE',
        sale__created_at__date__gte=timezone.now().date().replace(day=1)
    ).count()

    fiscalized_invoices = Invoice.objects.filter(
        sale__document_type='INVOICE',
        is_fiscalized=True
    ).count()

    pending_invoices = Invoice.objects.filter(
        sale__document_type='INVOICE',
        sale__payment_status__in=['PENDING', 'PARTIALLY_PAID']
    ).count()

    # Calculate average invoice amount safely
    avg_result = Invoice.objects.filter(
        sale__document_type='INVOICE'
    ).aggregate(avg_amount=Avg('sale__total_amount'))
    avg_invoice_amount = avg_result['avg_amount'] or 0

    # Performance metrics
    total_invoiced_amount = Invoice.objects.filter(
        sale__document_type='INVOICE'
    ).aggregate(
        Sum('sale__total_amount')
    )['sale__total_amount__sum'] or 0
    collection_rate = (total_revenue / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

    # On-time payment rate
    on_time_payments = Invoice.objects.filter(
        sale__document_type='INVOICE',
        sale__payment_status='PAID',
        payments__payment_date__lte=F('sale__due_date')
    ).distinct().count()

    total_paid_invoices = Invoice.objects.filter(
        sale__document_type='INVOICE',
        sale__payment_status='PAID'
    ).count()
    on_time_rate = (on_time_payments / total_paid_invoices * 100) if total_paid_invoices > 0 else 0

    fiscalization_rate = (fiscalized_invoices / total_invoices * 100) if total_invoices > 0 else 0

    # Average days to pay
    try:
        paid_invoices_with_payments = Invoice.objects.filter(
            sale__document_type='INVOICE',
            sale__payment_status='PAID',
            payments__isnull=False
        ).annotate(
            days_to_pay=ExpressionWrapper(
                F('payments__payment_date') - F('sale__created_at'),
                output_field=DurationField()
            )
        )

        avg_days_result = paid_invoices_with_payments.aggregate(
            avg_days=Avg('days_to_pay')
        )
        avg_days_to_pay = avg_days_result['avg_days']
        if avg_days_to_pay:
            avg_days_to_pay = avg_days_to_pay.days
        else:
            avg_days_to_pay = 0
    except (ValueError, TypeError):
        avg_days_to_pay = 0

    # Monthly trends data
    monthly_data = []
    for i in range(12):
        month_start = (end_date.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        month_invoices = Invoice.objects.filter(
            sale__document_type='INVOICE',
            sale__created_at__date__range=[month_start, month_end]
        )

        revenue = month_invoices.filter(
            sale__payment_status='PAID'
        ).aggregate(
            Sum('sale__total_amount')
        )['sale__total_amount__sum'] or 0

        monthly_data.append({
            'month': month_start.strftime('%Y-%m'),
            'month_name': month_start.strftime('%b'),
            'revenue': float(revenue),
            'count': month_invoices.count(),
        })

    monthly_data.reverse()

    # Status distribution - FIX: Use payment_status
    status_distribution = Invoice.objects.filter(
        sale__document_type='INVOICE'
    ).values('sale__payment_status').annotate(
        count=Count('id'),
        total_amount=Sum('sale__total_amount')
    ).order_by('sale__payment_status')

    status_data = []
    for item in status_distribution:
        count = item['count'] or 0
        total_amount = item['total_amount'] or 0
        percentage = (count / total_invoices * 100) if total_invoices > 0 else 0
        avg_amount = (total_amount / count) if count > 0 else 0

        # Get the status label from Sale model
        from sales.models import Sale
        status_label = dict(Sale.PAYMENT_STATUS_CHOICES).get(
            item['sale__payment_status'],
            item['sale__payment_status']
        )

        status_data.append({
            'status': item['sale__payment_status'],
            'label': status_label,
            'count': count,
            'total_amount': float(total_amount),
            'avg_amount': float(avg_amount),
            'percentage': round(percentage, 1)
        })

    # Payment methods distribution
    payment_methods_data = InvoicePayment.objects.values('payment_method').annotate(
        count=Count('id'),
        total=Sum('amount')
    ).order_by('-count')

    # Top customers
    top_customers = Invoice.objects.filter(
        sale__document_type='INVOICE',
        sale__customer__isnull=False
    ).values(
        'sale__customer__name'
    ).annotate(
        invoice_count=Count('id'),
        total_amount=Sum('sale__total_amount')
    ).order_by('-total_amount')[:5]

    # EFRIS compliance
    non_fiscalized_invoices = total_invoices - fiscalized_invoices

    context = {
        'total_invoices': total_invoices,
        'total_revenue': total_revenue,
        'pending_amount': pending_amount,
        'overdue_invoices': overdue_invoices,
        'invoices_this_month': invoices_this_month,
        'fiscalized_invoices': fiscalized_invoices,
        'pending_invoices': pending_invoices,
        'avg_invoice_amount': avg_invoice_amount,
        'collection_rate': round(collection_rate, 1),
        'on_time_rate': round(on_time_rate, 1),
        'fiscalization_rate': round(fiscalization_rate, 1),
        'avg_days_to_pay': avg_days_to_pay,
        'monthly_data': monthly_data,
        'status_data': status_data,
        'payment_methods_data': list(payment_methods_data),
        'top_customers': list(top_customers),
        'non_fiscalized_invoices': non_fiscalized_invoices,
        'start_date': start_date,
        'end_date': end_date,
    }

    return render(request, 'invoices/analytics.html', context)

@login_required
@permission_required('invoices.view_invoice')
def analytics_api(request):
    """API endpoint for analytics data"""
    try:
        period = int(request.GET.get('period', 12))
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        data = {
            'success': True,
            'metrics': {
                'total_invoices': Invoice.objects.count(),
                'total_revenue': float(
                    Invoice.objects.filter(sale__status='PAID').aggregate(
                        Sum('sale__total_amount')
                    )['sale__total_amount__sum'] or 0
                ),
            },
            'monthly_data': [],
            'status_data': [],
            'payment_methods_data': []
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@permission_required('invoices.view_invoice')
def invoice_print_view(request, pk):
    """Generate printable invoice"""
    company = get_current_tenant(request)
    if not company:
        return HttpResponse('No company context', status=403)
    with tenant_context(company):
        invoice = get_object_or_404(
            Invoice.objects.filter(sale__store__company=company),
            pk=pk
        )

        template = InvoiceTemplate.objects.filter(
            is_default=True
        ).first()

        if not template:
            template = InvoiceTemplate.objects.first()

        context = {
            'invoice': invoice,
            'template': template,
            'company_info': {
                'name': company.name,
                'address': company.physical_address,
                'phone': company.phone,
                'email': company.email,
                'tin': company.tin,
            }
        }

        return render(request, 'invoices/invoice_print.html', context)


@csrf_exempt
@login_required
def ajax_invoice_status(request):
    """AJAX endpoint for updating invoice status - FIXED VERSION"""

    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Invalid request method'
        })

    try:
        data = json.loads(request.body)
        invoice_id = data.get('invoice_id')
        new_status = data.get('status')

        # Validate required fields
        if not invoice_id or not new_status:
            return JsonResponse({
                'success': False,
                'error': 'Missing invoice_id or status'
            })

        invoice = Invoice.objects.select_related('sale').get(pk=invoice_id)

        # Validate status change
        if invoice.is_fiscalized and new_status in ['DRAFT']:
            return JsonResponse({
                'success': False,
                'error': 'Cannot change status of fiscalized invoice'
            })

        # Update the sale status instead of invoice status
        invoice.sale.status = new_status
        invoice.sale.save(update_fields=['status'])

        return JsonResponse({
            'success': True,
            'message': f'Invoice status updated to {invoice.sale.get_status_display()}'
        })

    except Invoice.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Invoice not found'
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        })

    except Exception as e:
        logger.error(f"Error updating invoice status: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@permission_required('invoices.view_invoice')
def invoice_dashboard(request):
    """Main dashboard with metrics including credit tracking"""
    company = get_current_tenant(request)
    if not company:
        messages.error(request, 'No company context found')
        return redirect('invoices:list')

    with tenant_context(company):
        today = timezone.now().date()
        this_month = today.replace(day=1)

        # Base queryset - filter by document_type
        invoices = Invoice.objects.filter(
            sale__store__company=company,
            sale__document_type='INVOICE'
        ).select_related('sale')

        # Debug: Check if we're finding invoices
        total_invoices = invoices.count()
        logger.info(f"DEBUG: Found {total_invoices} invoices for company {company.name}")

        invoices_this_month = invoices.filter(
            sale__created_at__gte=this_month  # FIXED: Use sale__created_at
        ).count()

        # FIX: Use payment_status
        paid_invoices = invoices.filter(sale__payment_status='PAID')
        total_revenue = paid_invoices.aggregate(
            total=Sum('sale__total_amount')
        )['total'] or 0

        pending_invoices = invoices.exclude(sale__payment_status='PAID')
        pending_amount = pending_invoices.aggregate(
            total=Sum('sale__total_amount')
        )['total'] or 0

        # FIX: Overdue calculation
        overdue_invoices = invoices.filter(
            sale__due_date__lt=today,
            sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
        ).count()

        fiscalized_invoices = invoices.filter(is_fiscalized=True).count()

        avg_invoice_amount = invoices.aggregate(
            avg=Avg('sale__total_amount')
        )['avg'] or 0

        # Calculate performance metrics
        total_invoiced_amount = invoices.aggregate(
            total=Sum('sale__total_amount')
        )['total'] or 0
        collection_rate = (total_revenue / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

        # Calculate on-time payment rate
        from django.db.models import F
        on_time_payments = InvoicePayment.objects.filter(
            invoice__in=invoices,
            invoice__sale__payment_status='PAID',
            payment_date__lte=F('invoice__sale__due_date')
        ).count()
        total_paid_invoices = paid_invoices.count()
        on_time_rate = (on_time_payments / total_paid_invoices * 100) if total_paid_invoices > 0 else 0

        fiscalization_rate = (fiscalized_invoices / total_invoices * 100) if total_invoices > 0 else 0

        # ADD: Credit invoice metrics
        credit_invoices = invoices.filter(sale__payment_method='CREDIT')
        cash_invoices = invoices.filter(sale__payment_method__in=['CASH', 'CARD', 'BANK_TRANSFER'])

        # Get detailed credit metrics
        total_credit_invoices = credit_invoices.count()
        total_cash_invoices = cash_invoices.count()

        credit_metrics = {
            'total_credit_invoices': total_credit_invoices,
            'credit_revenue': credit_invoices.filter(
                sale__payment_status='PAID'
            ).aggregate(Sum('sale__total_amount'))['sale__total_amount__sum'] or 0,
            'outstanding_credit': credit_invoices.filter(
                sale__payment_status__in=['PENDING', 'PARTIALLY_PAID']
            ).aggregate(Sum('sale__total_amount'))['sale__total_amount__sum'] or 0,
            'overdue_credit': credit_invoices.filter(
                sale__payment_status='OVERDUE'
            ).aggregate(Sum('sale__total_amount'))['sale__total_amount__sum'] or 0,
            'overdue_credit_count': credit_invoices.filter(
                sale__payment_status='OVERDUE'
            ).count(),
            'credit_collection_rate': (
                (credit_invoices.filter(sale__payment_status='PAID').count() / total_credit_invoices * 100)
                if total_credit_invoices > 0 else 0
            ),
            'credit_vs_cash_ratio': (
                (total_credit_invoices / total_invoices * 100)
                if total_invoices > 0 else 0
            ),
            'avg_credit_amount': credit_invoices.aggregate(
                avg=Avg('sale__total_amount')
            )['avg'] or 0,
            'avg_cash_amount': cash_invoices.aggregate(
                avg=Avg('sale__total_amount')
            )['avg'] or 0,
        }

        # Customer credit summary
        from customers.models import Customer
        credit_customers_summary = Customer.objects.filter(
            allow_credit=True,
            is_active=True
        ).aggregate(
            total_limit=Sum('credit_limit'),
            total_used=Sum('credit_balance'),
            total_available=Sum('credit_available'),
            customers_count=Count('id'),
            customers_good=Count('id', filter=Q(credit_status='GOOD')),
            customers_warning=Count('id', filter=Q(credit_status='WARNING')),
            customers_blocked=Count('id', filter=Q(credit_status__in=['SUSPENDED', 'BLOCKED'])),
            customers_at_risk=Count('id', filter=Q(
                credit_status__in=['WARNING', 'SUSPENDED', 'BLOCKED']
            ))
        )

        # Calculate credit utilization
        if credit_customers_summary['total_limit']:
            credit_utilization_percentage = (
                    credit_customers_summary['total_used'] / credit_customers_summary['total_limit'] * 100
            )
        else:
            credit_utilization_percentage = 0

        credit_customers_summary['utilization_percentage'] = round(credit_utilization_percentage, 1)

        # Recent activity
        recent_invoices = invoices.select_related(
            'sale__customer', 'sale__created_by'
        ).order_by('-sale__created_at')[:10]

        recent_payments = InvoicePayment.objects.filter(
            invoice__sale__store__company=company
        ).select_related(
            'invoice__sale', 'processed_by'
        ).order_by('-created_at')[:10]

        # Upcoming due dates
        upcoming_due = today + timedelta(days=7)
        upcoming_invoices_qs = invoices.filter(
            sale__due_date__range=[today, upcoming_due],
            sale__payment_status__in=['PENDING', 'PARTIALLY_PAID']
        ).select_related('sale__customer').order_by('sale__due_date')[:5]

        # Convert to list and add days_until_due
        upcoming_invoices = []
        for invoice in upcoming_invoices_qs:
            if invoice.sale.due_date:
                invoice.days_until_due = (invoice.sale.due_date - today).days
            else:
                invoice.days_until_due = 0
            upcoming_invoices.append(invoice)

        # Recent credit activity
        recent_credit_invoices = credit_invoices.select_related(
            'sale__customer', 'sale__created_by'
        ).order_by('-sale__created_at')[:5]

        # Top overdue credit invoices
        top_overdue_credit = credit_invoices.filter(
            sale__payment_status='OVERDUE'
        ).select_related(
            'sale__customer'
        ).order_by(
            'sale__due_date'
        )[:5]

        # Add overdue days to each
        for invoice in top_overdue_credit:
            if invoice.sale.due_date:
                invoice.overdue_days = (today - invoice.sale.due_date).days
            else:
                invoice.overdue_days = 0

        # Monthly credit trend
        from django.db.models.functions import TruncMonth
        monthly_credit_trend = credit_invoices.annotate(
            month=TruncMonth('sale__created_at')
        ).values('month').annotate(
            count=Count('id'),
            total=Sum('sale__total_amount'),
            paid=Sum('sale__total_amount', filter=Q(sale__payment_status='PAID'))
        ).order_by('month')[:6]

        context = {
            'metrics': {
                'total_invoices': total_invoices,
                'invoices_this_month': invoices_this_month,
                'total_revenue': total_revenue,
                'pending_amount': pending_amount,
                'pending_invoices': pending_invoices.count(),
                'overdue_invoices': overdue_invoices,
                'fiscalized_invoices': fiscalized_invoices,
                'avg_invoice_amount': avg_invoice_amount,
                'collection_rate': round(collection_rate, 1),
                'on_time_rate': round(on_time_rate, 1),
                'fiscalization_rate': round(fiscalization_rate, 1),
            },
            'credit_metrics': credit_metrics,
            'credit_customers_summary': credit_customers_summary,
            'recent_invoices': recent_invoices,
            'recent_payments': recent_payments,
            'recent_credit_invoices': recent_credit_invoices,
            'upcoming_invoices': upcoming_invoices,
            'top_overdue_credit': top_overdue_credit,
            'monthly_credit_trend': monthly_credit_trend,
            'EFRIS_ENABLED': getattr(company, 'efris_enabled', False),
        }

        return render(request, 'invoices/dashboard.html', context)


@login_required
@permission_required('invoices.view_invoice')
def dashboard_chart_data(request):
    """API endpoint for dashboard chart data"""
    period = int(request.GET.get('period', 12))
    today = timezone.now().date()
    start_date = today - timedelta(days=period * 30)

    # Monthly revenue data
    monthly_data = []
    current = start_date.replace(day=1)

    while current <= today:
        month_end = (current + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        # Use sale__created_at
        month_invoices = Invoice.objects.filter(
            sale__created_at__date__range=[current, month_end]
        )

        revenue = month_invoices.filter(sale__status='PAID').aggregate(
            Sum('sale__total_amount')
        )['sale__total_amount__sum'] or 0

        invoice_count = month_invoices.count()

        monthly_data.append({
            'month': current.strftime('%Y-%m'),
            'month_name': current.strftime('%b'),
            'revenue': float(revenue),
            'invoice_count': invoice_count
        })

        # Move to next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    # Status distribution
    status_distribution = Invoice.objects.values('sale__status').annotate(
        count=Count('id')
    ).order_by('sale__status')

    status_data = []
    from sales.models import Sale
    for item in status_distribution:
        status_data.append({
            'status': item['sale__status'],
            'label': dict(Sale.STATUS_CHOICES).get(
                item['sale__status'],
                item['sale__status']
            ),
            'count': item['count']
        })

    return JsonResponse({
        'monthly_data': monthly_data,
        'status_data': status_data,
        'success': True
    })


@login_required
@permission_required('invoices.view_invoice')
def dashboard_metrics(request):
    """API endpoint for real-time dashboard metrics"""
    today = timezone.now().date()
    this_month = today.replace(day=1)

    # Calculate metrics - Use payment_status and filter by document_type
    total_invoices = Invoice.objects.filter(sale__document_type='INVOICE').count()
    invoices_this_month = Invoice.objects.filter(
        sale__document_type='INVOICE',
        sale__created_at__date__gte=this_month
    ).count()

    paid_invoices = Invoice.objects.filter(
        sale__document_type='INVOICE',
        sale__payment_status='PAID'
    )
    total_revenue = paid_invoices.aggregate(
        Sum('sale__total_amount')
    )['sale__total_amount__sum'] or 0

    pending_invoices = Invoice.objects.filter(
        sale__document_type='INVOICE'
    ).exclude(
        sale__payment_status='PAID'
    )
    pending_amount = pending_invoices.aggregate(
        Sum('sale__total_amount')
    )['sale__total_amount__sum'] or 0

    overdue_invoices = Invoice.objects.filter(
        sale__document_type='INVOICE',
        sale__due_date__lt=today,
        sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
    ).count()

    fiscalized_invoices = Invoice.objects.filter(
        sale__document_type='INVOICE',
        is_fiscalized=True
    ).count()

    avg_invoice_amount = Invoice.objects.filter(
        sale__document_type='INVOICE'
    ).aggregate(
        avg_amount=Avg('sale__total_amount')
    )['avg_amount'] or 0

    total_invoiced_amount = Invoice.objects.filter(
        sale__document_type='INVOICE'
    ).aggregate(
        Sum('sale__total_amount')
    )['sale__total_amount__sum'] or 0
    collection_rate = (total_revenue / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

    on_time_payments = Invoice.objects.filter(
        sale__document_type='INVOICE',
        sale__payment_status='PAID',
        payments__payment_date__lte=F('sale__due_date')
    ).distinct().count()
    total_paid_invoices = paid_invoices.count()
    on_time_rate = (on_time_payments / total_paid_invoices * 100) if total_paid_invoices > 0 else 0

    fiscalization_rate = (fiscalized_invoices / total_invoices * 100) if total_invoices > 0 else 0

    metrics = {
        'total_invoices': total_invoices,
        'invoices_this_month': invoices_this_month,
        'total_revenue': float(total_revenue),
        'pending_amount': float(pending_amount),
        'pending_invoices': pending_invoices.count(),
        'overdue_invoices': overdue_invoices,
        'fiscalized_invoices': fiscalized_invoices,
        'avg_invoice_amount': float(avg_invoice_amount),
        'collection_rate': round(collection_rate, 1),
        'on_time_rate': round(on_time_rate, 1),
        'fiscalization_rate': round(fiscalization_rate, 1),
    }

    return JsonResponse({
        'metrics': metrics,
        'success': True
    })
