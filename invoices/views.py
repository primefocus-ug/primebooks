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

                # FIX: Use both status and payment_status
                status = form.cleaned_data.get('status')
                if status:
                    # Map to sale status/payment_status
                    queryset = queryset.filter(
                        Q(sale__status__in=status) | Q(sale__payment_status__in=status)
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

            return queryset.order_by('-sale__created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = InvoiceSearchForm(self.request.GET)
        return context

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
            'fiscalization_audits'
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

        context.update({
            'can_fiscalize': can_fiscalize,
            'fiscalize_message': fiscalization_error,
            'efris_status': efris_status,
            'fiscalization_history': invoice.fiscalization_audits.order_by(
                '-timestamp'
            )[:10],
        })

        return context


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
            # Check if sale is already an invoice
            if form.cleaned_data['sale'].document_type == 'INVOICE':
                messages.error(
                    self.request,
                    'This sale is already an invoice'
                )
                return self.form_invalid(form)

            # Update sale document type
            sale = form.cleaned_data['sale']
            sale.document_type = 'INVOICE'
            sale.save()

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
                payment = form.save(commit=False)
                payment.invoice = invoice
                payment.processed_by = request.user
                payment.save()

                messages.success(
                    request,
                    f'Payment of {payment.amount:,.2f} recorded successfully.'
                )

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': 'Payment recorded successfully',
                        'new_status': invoice.status,
                        'amount_outstanding': float(invoice.amount_outstanding)
                    })

                return redirect('invoices:detail', pk=invoice.pk)

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'errors': form.errors
                })

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
    """Main dashboard with metrics"""
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

        # Metrics
        total_invoices = invoices.count()
        invoices_this_month = invoices.filter(
            created_at__gte=this_month
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

        # Recent activity
        recent_invoices = invoices.select_related(
            'sale__customer', 'created_by'
        ).order_by('-created_at')[:10]

        recent_payments = InvoicePayment.objects.filter(
            invoice__sale__store__company=company
        ).select_related(
            'invoice__sale', 'processed_by'
        ).order_by('-created_at')[:10]

        # Upcoming due dates
        upcoming_due = today + timedelta(days=7)
        upcoming_invoices = invoices.filter(
            sale__due_date__range=[today, upcoming_due],
            sale__payment_status__in=['PENDING', 'PARTIALLY_PAID']
        ).select_related('sale__customer').order_by('sale__due_date')[:5]

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
            },
            'recent_invoices': recent_invoices,
            'recent_payments': recent_payments,
            'upcoming_invoices': upcoming_invoices,
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
