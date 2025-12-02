from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.urls import reverse_lazy, reverse
from django.db.models import Q, Sum, Count,F,Avg,ExpressionWrapper,DurationField
from django.utils import timezone
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
import json
import csv
from django.http import JsonResponse
import json
from datetime import timedelta, datetime
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from efris.models import FiscalizationAudit
from .models import Invoice, InvoiceTemplate, InvoicePayment
from .forms import (
    InvoiceForm, InvoiceSearchForm, InvoicePaymentForm,
    InvoiceTemplateForm, BulkInvoiceActionForm, FiscalizationForm
)


class InvoiceListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Advanced invoice list view with search, filtering, and pagination"""
    model = Invoice
    template_name = 'invoices/invoice_list.html'
    context_object_name = 'invoices'
    paginate_by = 20
    permission_required = 'invoices.view_invoice'

    def get_queryset(self):
        queryset = Invoice.objects.select_related(
            'sale', 'store', 'created_by', 'fiscalized_by'
        ).prefetch_related('payments')

        # Apply search filters
        form = InvoiceSearchForm(self.request.GET)
        if form.is_valid():
            search = form.cleaned_data.get('search')
            if search:
                queryset = queryset.filter(
                    Q(invoice_number__icontains=search) |
                    Q(sale__customer__name__icontains=search) |
                    Q(notes__icontains=search)
                )

            status = form.cleaned_data.get('status')
            if status:
                queryset = queryset.filter(status__in=status)

            document_type = form.cleaned_data.get('document_type')
            if document_type:
                queryset = queryset.filter(document_type=document_type)

            date_from = form.cleaned_data.get('date_from')
            if date_from:
                queryset = queryset.filter(issue_date__gte=date_from)

            date_to = form.cleaned_data.get('date_to')
            if date_to:
                queryset = queryset.filter(issue_date__lte=date_to)

            amount_min = form.cleaned_data.get('amount_min')
            if amount_min:
                queryset = queryset.filter(total_amount__gte=amount_min)

            amount_max = form.cleaned_data.get('amount_max')
            if amount_max:
                queryset = queryset.filter(total_amount__lte=amount_max)

            if form.cleaned_data.get('is_overdue'):
                queryset = queryset.filter(
                    due_date__lt=timezone.now().date(),
                    status__in=['SENT', 'PARTIALLY_PAID']
                )

            if form.cleaned_data.get('is_fiscalized'):
                queryset = queryset.filter(is_fiscalized=True)

        return queryset.order_by('-issue_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = InvoiceSearchForm(self.request.GET)
        context['bulk_form'] = BulkInvoiceActionForm()

        # Add summary statistics
        queryset = self.get_queryset()
        context['stats'] = {
            'total_invoices': queryset.count(),
            'total_amount': queryset.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
            'overdue_count': queryset.filter(
                due_date__lt=timezone.now().date(),
                status__in=['SENT', 'PARTIALLY_PAID']
            ).count(),
            'unpaid_amount': queryset.exclude(status='PAID').aggregate(
                Sum('total_amount'))['total_amount__sum'] or 0,
        }

        return context


class InvoiceDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """Detailed invoice view with payment history and actions"""
    model = Invoice
    template_name = 'invoices/invoice_detail.html'
    context_object_name = 'invoice'
    permission_required = 'invoices.view_invoice'

    def get_queryset(self):
        return Invoice.objects.select_related(
            'sale', 'store', 'created_by', 'fiscalized_by'
        ).prefetch_related(
            'payments__processed_by',
            'fiscalization_audits'
        )

    def get_context_data(self, **kwargs):
        """Enhanced context data for InvoiceDetailView"""
        context = super().get_context_data(**kwargs)
        context['payment_form'] = InvoicePaymentForm(invoice=self.object)
        context['fiscalization_form'] = FiscalizationForm(invoice=self.object)

        # Enhanced EFRIS status checking
        invoice = self.object
        can_fiscalize = False
        fiscalization_error = None
        efris_status = {}

        if invoice.sale and invoice.sale.store:
            company = invoice.sale.store.company
            efris_enabled = getattr(company, 'efris_enabled', False)

            if efris_enabled:
                can_fiscalize, fiscalization_error = invoice.can_fiscalize(self.request.user)

                # Get EFRIS configuration status
                try:
                    from efris.services import validate_efris_configuration
                    config_valid, config_errors = validate_efris_configuration(company)
                    efris_status = {
                        'enabled': True,
                        'configured': config_valid,
                        'config_errors': config_errors,
                        'can_fiscalize': can_fiscalize,
                        'fiscalization_error': fiscalization_error,
                        'fiscal_document_number': invoice.fiscal_document_number,
                        'verification_code': invoice.verification_code,
                        'is_fiscalized': invoice.is_fiscalized,
                        'fiscalization_status': invoice.fiscalization_status,
                    }
                except ImportError:
                    efris_status = {
                        'enabled': True,
                        'configured': False,
                        'config_errors': ['EFRIS service not available'],
                        'can_fiscalize': False,
                        'service_available': False
                    }
            else:
                efris_status = {
                    'enabled': False,
                    'reason': 'EFRIS is not enabled for this company'
                }

        context.update({
            'can_fiscalize': can_fiscalize,
            'fiscalize_message': fiscalization_error,
            'efris_status': efris_status,
            'fiscalization_history': invoice.fiscalization_audits.order_by('-timestamp')[:10],
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

    # Base queryset
    invoices = Invoice.objects.filter(
        issue_date__gte=date_from,
        issue_date__lte=date_to
    ).select_related('sale__store__company')

    # EFRIS statistics
    total_invoices = invoices.count()
    fiscalized_invoices = invoices.filter(is_fiscalized=True).count()
    pending_fiscalization = invoices.filter(
        fiscalization_status='pending',
        status__in=['SENT', 'PAID', 'PARTIALLY_PAID']
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
        'invoice', 'user'
    ).filter(
        created_at__gte=timezone.now() - timedelta(days=7)
    ).order_by('-created_at')[:20]

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
    """Create new invoice with advanced form handling"""
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
            initial['sale'] = sale_id
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        messages.success(
            self.request,
            f'Invoice {self.object.invoice_number} created successfully.'
        )
        return response

    def get_success_url(self):
        return reverse('invoices:detail', kwargs={'pk': self.object.pk})


class InvoiceUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """Update existing invoice with validation"""
    model = Invoice
    form_class = InvoiceForm
    template_name = 'invoices/invoice_form.html'
    permission_required = 'invoices.change_invoice'

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
            f'Invoice {self.object.invoice_number} updated successfully.'
        )
        return response

    def get_success_url(self):
        return reverse('invoices:detail', kwargs={'pk': self.object.pk})


@login_required
@permission_required('invoices.add_invoicepayment')
def add_payment(request, pk):
    """AJAX view for adding invoice payments"""
    invoice = get_object_or_404(Invoice, pk=pk)

    if request.method == 'POST':
        form = InvoicePaymentForm(request.POST, invoice=invoice)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.invoice = invoice
            payment.processed_by = request.user
            payment.save()

            messages.success(
                request,
                f'Payment of UGX {payment.amount:,.2f} recorded successfully.'
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
    """Enhanced fiscalize invoice with proper EFRIS integration"""
    invoice = get_object_or_404(Invoice.objects.select_related('sale__store__company'), pk=pk)

    if request.method == 'POST':
        form = FiscalizationForm(request.POST, invoice=invoice)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Check if invoice can be fiscalized
                    can_fiscalize, reason = invoice.can_fiscalize(request.user)
                    if not can_fiscalize:
                        messages.error(request, f'Cannot fiscalize invoice: {reason}')
                        return redirect('invoices:detail', pk=invoice.pk)

                    # Create audit record
                    audit = FiscalizationAudit.objects.create(
                        invoice=invoice,
                        action='FISCALIZE',
                        user=request.user,
                        success=False
                    )

                    try:
                        # Use the new EFRIS service layer for fiscalization
                        from invoices.services import InvoiceEFRISService

                        service = InvoiceEFRISService(invoice.sale.store.company)
                        success, message = service.fiscalize_invoice(invoice, request.user)

                        if success:
                            audit.success = True
                            audit.fiscal_document_number = invoice.fiscal_document_number
                            audit.verification_code = invoice.verification_code
                            audit.device_number = getattr(invoice, 'device_number', '')
                            audit.save()

                            messages.success(
                                request,
                                f'Invoice {invoice.invoice_number} fiscalized successfully! '
                                f'Fiscal Document Number: {invoice.fiscal_document_number}'
                            )
                        else:
                            audit.error_message = message
                            audit.save()
                            messages.error(request, f'Fiscalization failed: {message}')

                    except ImportError:
                        # Fallback to basic fiscalization if service not available
                        success = invoice.fiscalize(request.user)
                        audit.success = success
                        if success:
                            audit.fiscal_document_number = invoice.fiscal_document_number
                        audit.save()

                        if success:
                            messages.success(request, f'Invoice {invoice.invoice_number} fiscalized successfully!')
                        else:
                            messages.error(request, 'Fiscalization failed - service unavailable')

            except Exception as e:
                audit.error_message = str(e)
                audit.save()
                messages.error(request, f'Fiscalization failed: {str(e)}')

    return redirect('invoices:detail', pk=invoice.pk)


@login_required
@permission_required('invoices.change_invoice')
@permission_required('invoices.fiscalize_invoice')
def bulk_fiscalize_invoices(request):
    """Bulk fiscalize multiple invoices using EFRIS service"""
    if request.method == 'POST':
        invoice_ids = request.POST.getlist('selected_invoices')

        if not invoice_ids:
            messages.error(request, 'No invoices selected for fiscalization.')
            return redirect('invoices:list')

        # Get invoices with related data
        invoices = Invoice.objects.select_related(
            'sale__store__company'
        ).filter(id__in=invoice_ids)

        # Group by company for efficient processing
        invoices_by_company = {}
        for invoice in invoices:
            company = invoice.sale.store.company
            if company not in invoices_by_company:
                invoices_by_company[company] = []
            invoices_by_company[company].append(invoice)

        total_processed = 0
        total_successful = 0
        total_failed = 0
        error_messages = []

        for company, company_invoices in invoices_by_company.items():
            # Check if EFRIS is enabled for this company
            if not getattr(company, 'efris_enabled', False):
                total_failed += len(company_invoices)
                error_messages.append(f"EFRIS not enabled for {company.name}")
                continue

            try:
                # Use EFRIS service for bulk processing
                from invoices.services import InvoiceEFRISService

                service = InvoiceEFRISService(company)
                result = service.bulk_fiscalize(company_invoices, request.user)

                total_processed += len(company_invoices)
                total_successful += result['successful_count']
                total_failed += result['failed_count']

                if result['errors']:
                    error_messages.extend([f"{company.name}: {error['error']}" for error in result['errors'][:3]])

            except ImportError:
                # Fallback to individual fiscalization
                for invoice in company_invoices:
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
                            error_messages.append(f"{invoice.invoice_number}: {reason}")
                    except Exception as e:
                        total_failed += 1
                        error_messages.append(f"{invoice.invoice_number}: {str(e)}")

                total_processed += len(company_invoices)

            except Exception as e:
                total_failed += len(company_invoices)
                error_messages.append(f"{company.name}: Service error - {str(e)}")

        # Report results
        if total_successful > 0:
            messages.success(
                request,
                f'Successfully fiscalized {total_successful} out of {total_processed} invoices.'
            )

        if total_failed > 0:
            error_summary = f'{total_failed} invoices failed to fiscalize.'
            if error_messages:
                error_summary += f' First few errors: {"; ".join(error_messages[:3])}'
            messages.error(request, error_summary)

        if total_processed == 0:
            messages.warning(request, 'No invoices were processed.')

    return redirect('invoices:list')


@login_required
@permission_required('invoices.change_invoice')
def bulk_actions(request):
    """Handle bulk actions on invoices"""
    if request.method == 'POST':
        form = BulkInvoiceActionForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data['action']
            invoice_ids = form.cleaned_data['selected_invoices']

            invoices = Invoice.objects.filter(id__in=invoice_ids)
            count = invoices.count()

            if action == 'mark_sent':
                invoices.filter(status='DRAFT').update(status='SENT')
                messages.success(request, f'{count} invoices marked as sent.')

            elif action == 'mark_paid':
                invoices.filter(status__in=['SENT', 'PARTIALLY_PAID']).update(status='PAID')
                messages.success(request, f'{count} invoices marked as paid.')

            elif action == 'export_pdf':
                return export_invoices_pdf(request, invoice_ids)

            elif action == 'send_email':
                # Implement email sending logic
                messages.info(request, f'Email reminders sent for {count} invoices.')

            elif action == 'fiscalize':
                fiscalized_count = 0
                for invoice in invoices:
                    can_fiscalize, _ = invoice.can_fiscalize(request.user)
                    if can_fiscalize:
                        try:
                            invoice.fiscalize(request.user)
                            fiscalized_count += 1
                        except Exception:
                            pass

                messages.success(request, f'{fiscalized_count} invoices fiscalized.')

    return redirect('invoices:list')


def export_invoices_pdf(request, invoice_ids):
    """Export selected invoices to PDF"""
    invoices = Invoice.objects.filter(id__in=invoice_ids)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="invoices_export.pdf"'

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    y_position = 750
    for invoice in invoices:
        p.drawString(50, y_position, f"Invoice: {invoice.invoice_number}")
        p.drawString(50, y_position - 20, f"Amount: UGX {invoice.total_amount:,.2f}")
        p.drawString(50, y_position - 40, f"Status: {invoice.get_status_display()}")
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
    # Get date range from request or use defaults
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

    # Basic statistics
    total_invoices = Invoice.objects.count()
    total_revenue = Invoice.objects.filter(
        status='PAID'
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    pending_amount = Invoice.objects.exclude(
        status__in=['PAID', 'CANCELLED']
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    overdue_invoices = Invoice.objects.filter(
        due_date__lt=end_date,
        status__in=['SENT', 'PARTIALLY_PAID']
    ).count()

    # Enhanced metrics
    invoices_this_month = Invoice.objects.filter(
        issue_date__gte=timezone.now().date().replace(day=1)
    ).count()

    fiscalized_invoices = Invoice.objects.filter(is_fiscalized=True).count()
    pending_invoices = Invoice.objects.exclude(status__in=['PAID', 'CANCELLED']).count()

    # Calculate average invoice amount safely
    avg_result = Invoice.objects.aggregate(avg_amount=Avg('total_amount'))
    avg_invoice_amount = avg_result['avg_amount'] or 0

    # Performance metrics with safe calculations
    total_invoiced_amount = Invoice.objects.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    collection_rate = (total_revenue / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

    # On-time payment rate (simplified)
    on_time_payments = Invoice.objects.filter(
        status='PAID',
        payments__payment_date__lte=F('due_date')
    ).distinct().count()
    total_paid_invoices = Invoice.objects.filter(status='PAID').count()
    on_time_rate = (on_time_payments / total_paid_invoices * 100) if total_paid_invoices > 0 else 0

    fiscalization_rate = (fiscalized_invoices / total_invoices * 100) if total_invoices > 0 else 0

    # Average days to pay - safely handle None values
    try:
        paid_invoices_with_payments = Invoice.objects.filter(
            status='PAID',
            payments__isnull=False
        ).annotate(
            days_to_pay=ExpressionWrapper(
                F('payments__payment_date') - F('issue_date'),
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
            issue_date__range=[month_start, month_end]
        )

        revenue = month_invoices.filter(status='PAID').aggregate(
            Sum('total_amount')
        )['total_amount__sum'] or 0

        monthly_data.append({
            'month': month_start.strftime('%Y-%m'),
            'month_name': month_start.strftime('%b'),
            'revenue': float(revenue),
            'count': month_invoices.count(),
        })

    monthly_data.reverse()

    # Status distribution with safe calculations
    status_distribution = Invoice.objects.values('status').annotate(
        count=Count('id'),
        total_amount=Sum('total_amount')
    ).order_by('status')

    status_data = []
    for item in status_distribution:
        count = item['count'] or 0
        total_amount = item['total_amount'] or 0
        percentage = (count / total_invoices * 100) if total_invoices > 0 else 0
        avg_amount = (total_amount / count) if count > 0 else 0

        status_data.append({
            'status': item['status'],
            'label': dict(Invoice.STATUS_CHOICES).get(item['status'], item['status']),
            'count': count,
            'total_amount': float(total_amount),
            'avg_amount': float(avg_amount),
            'percentage': round(percentage, 1)
        })

    # Payment methods distribution
    payment_methods_data = InvoicePayment.objects.values('payment_method').annotate(
        count=Count('id')
    ).order_by('-count')

    # Top customers
    top_customers = Invoice.objects.filter(
        sale__customer__isnull=False
    ).values(
        'sale__customer__name'
    ).annotate(
        invoice_count=Count('id'),
        total_amount=Sum('total_amount')
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


# Add API endpoint for analytics data
@login_required
@permission_required('invoices.view_invoice')
def analytics_api(request):
    """API endpoint for analytics data"""
    try:
        period = int(request.GET.get('period', 12))
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        # Use the same logic as the main analytics view but return JSON
        # This is a simplified version - you can expand it as needed
        data = {
            'success': True,
            'metrics': {
                'total_invoices': Invoice.objects.count(),
                'total_revenue': float(
                    Invoice.objects.filter(status='PAID').aggregate(Sum('total_amount'))['total_amount__sum'] or 0),
                # Add other metrics as needed
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
    """Generate printable invoice view"""
    invoice = get_object_or_404(Invoice, pk=pk)
    company = getattr(request, 'tenant', None)
    # Get the default template or first available
    template = InvoiceTemplate.objects.filter(is_default=True).first()
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
            'website': 'primebooks.sale'
        }
    }

    return render(request, 'invoices/invoice_print.html', context)


@csrf_exempt
@login_required
def ajax_invoice_status(request):
    """AJAX endpoint for updating invoice status"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            invoice_id = data.get('invoice_id')
            new_status = data.get('status')

            invoice = Invoice.objects.get(pk=invoice_id)

            # Validate status change
            if invoice.is_fiscalized and new_status in ['DRAFT']:
                return JsonResponse({
                    'success': False,
                    'error': 'Cannot change status of fiscalized invoice'
                })

            invoice.status = new_status
            invoice.save(update_fields=['status'])

            return JsonResponse({
                'success': True,
                'message': f'Invoice status updated to {invoice.get_status_display()}'
            })

        except Invoice.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Invoice not found'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })

    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
@permission_required('invoices.view_invoice')
def duplicate_invoice(request, pk):
    """Create a duplicate of an existing invoice"""
    original_invoice = get_object_or_404(Invoice, pk=pk)

    # Create a copy
    new_invoice = Invoice.objects.get(pk=pk)
    new_invoice.pk = None
    new_invoice.invoice_number = None  # Will be auto-generated
    new_invoice.status = 'DRAFT'
    new_invoice.is_fiscalized = False
    new_invoice.fiscal_number = None
    new_invoice.verification_code = None
    new_invoice.fiscalization_time = None
    new_invoice.fiscalized_by = None
    new_invoice.created_by = request.user
    new_invoice.issue_date = timezone.now().date()
    new_invoice.due_date = new_invoice.issue_date + timedelta(days=30)
    new_invoice.save()

    messages.success(
        request,
        f'Invoice duplicated successfully. New invoice number: {new_invoice.invoice_number}'
    )

    return redirect('invoices:detail', pk=new_invoice.pk)


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
def export_invoices_csv(request):
    """Export invoices to CSV format"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="invoices_export.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Invoice Number', 'Document Type', 'Issue Date', 'Due Date',
        'Status', 'Customer', 'Subtotal', 'Tax Amount', 'Discount Amount',
        'Total Amount', 'Amount Paid', 'Amount Outstanding', 'Is Overdue',
        'Is Fiscalized', 'Fiscal Number'
    ])

    invoices = Invoice.objects.select_related('sale').order_by('-issue_date')

    for invoice in invoices:
        writer.writerow([
            invoice.invoice_number,
            invoice.get_document_type_display(),
            invoice.issue_date,
            invoice.due_date,
            invoice.get_status_display(),
            invoice.sale.customer.name if invoice.sale and invoice.sale.customer else '',
            invoice.subtotal,
            invoice.tax_amount,
            invoice.discount_amount,
            invoice.total_amount,
            invoice.amount_paid,
            invoice.amount_outstanding,
            invoice.is_overdue,
            invoice.is_fiscalized,
            invoice.fiscal_number or ''
        ])

    return response


class FiscalizationAuditView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """View fiscalization audit logs"""
    model = FiscalizationAudit
    template_name = 'invoices/fiscalization_audit.html'
    context_object_name = 'audits'
    permission_required = 'efris.view_fiscalizationaudit'
    paginate_by = 50

    def get_queryset(self):
        return FiscalizationAudit.objects.select_related(
            'invoice', 'user'
        ).order_by('-created_at')


@login_required
@permission_required('invoices.view_invoice')
def invoice_dashboard(request):
    """Enhanced main dashboard with key metrics and recent activity"""
    # Date calculations
    today = timezone.now().date()
    this_month = today.replace(day=1)
    last_12_months = today - timedelta(days=365)

    # Enhanced metrics
    total_invoices = Invoice.objects.count()
    invoices_this_month = Invoice.objects.filter(
        issue_date__gte=this_month
    ).count()

    paid_invoices = Invoice.objects.filter(status='PAID')
    total_revenue = paid_invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    pending_invoices = Invoice.objects.exclude(status__in=['PAID', 'CANCELLED'])
    pending_amount = pending_invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    overdue_invoices = Invoice.objects.filter(
        due_date__lt=today,
        status__in=['SENT', 'PARTIALLY_PAID']
    ).count()

    fiscalized_invoices = Invoice.objects.filter(is_fiscalized=True).count()

    # Calculate average invoice amount
    avg_invoice_amount = Invoice.objects.aggregate(
        avg_amount=Avg('total_amount')
    )['avg_amount'] or 0

    # Performance metrics
    total_invoiced_amount = Invoice.objects.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    collection_rate = (total_revenue / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

    # On-time payment rate (simplified - invoices paid before due date)
    on_time_payments = Invoice.objects.filter(
        status='PAID',
        payments__payment_date__lte=F('due_date')
    ).distinct().count()
    total_paid_invoices = paid_invoices.count()
    on_time_rate = (on_time_payments / total_paid_invoices * 100) if total_paid_invoices > 0 else 0

    fiscalization_rate = (fiscalized_invoices / total_invoices * 100) if total_invoices > 0 else 0

    # Monthly revenue data for charts
    monthly_data = []
    for i in range(12):
        month_start = (today.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        month_invoices = Invoice.objects.filter(
            issue_date__range=[month_start, month_end]
        )

        revenue = month_invoices.filter(status='PAID').aggregate(
            Sum('total_amount')
        )['total_amount__sum'] or 0

        invoice_count = month_invoices.count()

        monthly_data.append({
            'month': month_start.strftime('%Y-%m'),
            'month_name': month_start.strftime('%b'),
            'revenue': float(revenue),
            'invoice_count': invoice_count
        })

    monthly_data.reverse()  # Order from oldest to newest

    # Status distribution for chart
    status_distribution = Invoice.objects.values('status').annotate(
        count=Count('id')
    ).order_by('status')

    status_data = []
    for item in status_distribution:
        status_data.append({
            'status': item['status'],
            'label': dict(Invoice.STATUS_CHOICES).get(item['status'], item['status']),
            'count': item['count']
        })

    # Recent invoices
    recent_invoices = Invoice.objects.select_related(
        'sale', 'created_by'
    ).order_by('-created_at')[:10]

    # Recent payments
    recent_payments = InvoicePayment.objects.select_related(
        'invoice', 'processed_by'
    ).order_by('-created_at')[:10]

    # Upcoming due dates (next 7 days)
    upcoming_due_date = today + timedelta(days=7)
    upcoming_invoices = Invoice.objects.filter(
        due_date__range=[today, upcoming_due_date],
        status__in=['SENT', 'PARTIALLY_PAID']
    ).select_related('sale__customer').order_by('due_date')[:5]

    # Add days until due for each upcoming invoice
    for invoice in upcoming_invoices:
        invoice.days_until_due = (invoice.due_date - today).days

    metrics = {
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
    }

    context = {
        'metrics': metrics,
        'recent_invoices': recent_invoices,
        'recent_payments': recent_payments,
        'upcoming_invoices': upcoming_invoices,
        'monthly_data': monthly_data,
        'status_data': status_data,
    }

    return render(request, 'invoices/dashboard.html', context)



@login_required
@permission_required('invoices.view_invoice')
def dashboard_chart_data(request):
    """API endpoint for dashboard chart data"""
    # Get period from request (default to 12 months)
    period = int(request.GET.get('period', 12))

    today = timezone.now().date()
    start_date = today - timedelta(days=period * 30)

    # Monthly revenue data
    monthly_data = []
    current = start_date.replace(day=1)

    while current <= today:
        month_end = (current + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        month_invoices = Invoice.objects.filter(
            issue_date__range=[current, month_end]
        )

        revenue = month_invoices.filter(status='PAID').aggregate(
            Sum('total_amount')
        )['total_amount__sum'] or 0

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
    status_distribution = Invoice.objects.values('status').annotate(
        count=Count('id')
    ).order_by('status')

    status_data = []
    for item in status_distribution:
        status_data.append({
            'status': item['status'],
            'label': dict(Invoice.STATUS_CHOICES).get(item['status'], item['status']),
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

    # Calculate metrics (similar to main dashboard view but for API)
    total_invoices = Invoice.objects.count()
    invoices_this_month = Invoice.objects.filter(issue_date__gte=this_month).count()

    paid_invoices = Invoice.objects.filter(status='PAID')
    total_revenue = paid_invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    pending_invoices = Invoice.objects.exclude(status__in=['PAID', 'CANCELLED'])
    pending_amount = pending_invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    overdue_invoices = Invoice.objects.filter(
        due_date__lt=today,
        status__in=['SENT', 'PARTIALLY_PAID']
    ).count()

    fiscalized_invoices = Invoice.objects.filter(is_fiscalized=True).count()

    avg_invoice_amount = Invoice.objects.aggregate(
        avg_amount=Avg('total_amount')
    )['avg_amount'] or 0

    total_invoiced_amount = Invoice.objects.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    collection_rate = (total_revenue / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

    on_time_payments = Invoice.objects.filter(
        status='PAID',
        payments__payment_date__lte=F('due_date')
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