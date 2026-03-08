import csv
import logging
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, Http404, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, DetailView, TemplateView
from datetime import timedelta

from ..models import Company

logger = logging.getLogger(__name__)


class BillingHistoryView(LoginRequiredMixin, ListView):
    """
    View billing history and invoices
    """
    template_name = 'company/billing/history.html'
    context_object_name = 'invoices'
    # TODO: restore paginate_by = 20 once get_queryset returns a real QuerySet.
    # ListView pagination requires a QuerySet; returning a plain list disables it safely.
    paginate_by = None

    def get_queryset(self):
        company = getattr(self.request.user, 'company', None)
        if not company:
            return []

        # TODO: Replace with actual Invoice model when created
        # For now, return placeholder data
        return self._get_placeholder_invoices(company)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = getattr(self.request.user, 'company', None)

        if company:
            context['company'] = company
            context['total_paid'] = self._calculate_total_paid(company)
            context['next_billing_date'] = company.next_billing_date
            context['current_plan'] = company.plan

        return context

    def _get_placeholder_invoices(self, company):
        """
        Placeholder invoice data
        TODO: Replace with actual Invoice.objects.filter(company=company)
        """
        invoices = []

        # Last payment
        if company.last_payment_date:
            invoices.append({
                'id': f'INV-{company.company_id}-001',
                'date': company.last_payment_date,
                'amount': company.plan.price if company.plan else 0,
                'status': 'PAID',
                'description': f'{company.plan.display_name} Subscription' if company.plan else 'Payment',
            })

        return invoices

    def _calculate_total_paid(self, company):
        """Calculate total amount paid"""
        # TODO: Sum actual invoices
        if company.last_payment_date and company.plan:
            return company.plan.price
        return 0


class InvoiceDetailView(LoginRequiredMixin, DetailView):
    """
    View detailed invoice information
    """
    template_name = 'company/billing/invoice_detail.html'
    context_object_name = 'invoice'

    def get_object(self, queryset=None):
        company = getattr(self.request.user, 'company', None)
        if not company:
            raise Http404("No company found")

        invoice_id = self.kwargs.get('invoice_id')

        # TODO: Get actual invoice
        # invoice = Invoice.objects.get(id=invoice_id, company=company)

        # Placeholder
        return {
            'id': invoice_id,
            'company': company,
            'date': company.last_payment_date or timezone.now().date(),
            'amount': company.plan.price if company.plan else 0,
            'status': 'PAID',
            'items': [
                {
                    'description': f'{company.plan.display_name} Subscription' if company.plan else 'Service',
                    'amount': company.plan.price if company.plan else 0,
                }
            ]
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['company'] = getattr(self.request.user, 'company', None)
        return context


class DownloadInvoiceView(LoginRequiredMixin, View):
    """
    Download invoice as PDF
    """

    def get(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            raise Http404("No company found")

        invoice_id = kwargs.get('invoice_id')

        # TODO: Generate actual PDF using reportlab or weasyprint
        # from django.template.loader import render_to_string
        # from weasyprint import HTML

        # invoice = Invoice.objects.get(id=invoice_id, company=company)
        # html_string = render_to_string('company/billing/invoice_pdf.html', {'invoice': invoice})
        # pdf = HTML(string=html_string).write_pdf()

        # For now, return placeholder response
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="invoice_{invoice_id}.pdf"'
        response.write(b'%PDF-1.4 Placeholder Invoice PDF')

        return response


class PaymentMethodsView(LoginRequiredMixin, TemplateView):
    """
    Manage payment methods
    """
    template_name = 'company/billing/payment_methods.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = getattr(self.request.user, 'company', None)

        if company:
            context['company'] = company
            context['current_payment_method'] = company.payment_method
            context['payment_methods'] = self._get_payment_methods(company)

        return context

    def _get_payment_methods(self, company):
        """
        Get saved payment methods
        TODO: Integrate with payment gateway to fetch saved cards/methods
        """
        methods = []

        if company.payment_method:
            methods.append({
                'id': 'pm_default',
                'type': company.payment_method,
                'is_default': True,
                'details': f'{company.payment_method.title()} (Default)',
            })

        return methods


class AddPaymentMethodView(LoginRequiredMixin, View):
    """
    Add new payment method
    """

    def post(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        payment_type = request.POST.get('payment_type', '').strip()
        if not payment_type:
            return JsonResponse({
                'success': False,
                'message': 'Payment type is required'
            }, status=400)

        # TODO: Integrate with payment gateway
        # Example for Stripe:
        # stripe.PaymentMethod.attach(
        #     payment_method_id,
        #     customer=company.stripe_customer_id,
        # )

        company.payment_method = payment_type
        company.save(update_fields=['payment_method'])

        logger.info(f"Payment method added for company {company.company_id}")

        return JsonResponse({
            'success': True,
            'message': 'Payment method added successfully'
        })


class RemovePaymentMethodView(LoginRequiredMixin, View):
    """
    Remove payment method
    """

    def post(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        method_id = request.POST.get('method_id')

        # TODO: Remove from payment gateway

        return JsonResponse({
            'success': True,
            'message': 'Payment method removed successfully'
        })


class ProcessPaymentView(LoginRequiredMixin, View):
    """
    Process a payment
    """

    def post(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        raw_amount = request.POST.get('amount', '').strip()
        payment_method = request.POST.get('payment_method', '').strip()
        description = request.POST.get('description', 'Subscription payment')

        # Validate amount before touching any gateway
        try:
            from decimal import Decimal, InvalidOperation
            amount = Decimal(raw_amount)
            if amount <= 0:
                raise ValueError('Amount must be positive')
        except (InvalidOperation, ValueError, TypeError):
            return JsonResponse({
                'success': False,
                'message': f'Invalid amount: {raw_amount!r}'
            }, status=400)

        try:
            # TODO: Process payment through gateway
            # Example for Stripe:
            # charge = stripe.Charge.create(
            #     amount=int(float(amount) * 100),  # Convert to cents
            #     currency=company.preferred_currency.lower(),
            #     customer=company.stripe_customer_id,
            #     description=description,
            # )

            # Create invoice record
            # invoice = Invoice.objects.create(
            #     company=company,
            #     amount=amount,
            #     payment_method=payment_method,
            #     description=description,
            #     status='PAID',
            #     transaction_id=charge.id,
            # )

            logger.info(f"Payment processed for company {company.company_id}: ${amount}")

            return JsonResponse({
                'success': True,
                'message': 'Payment processed successfully',
                'transaction_id': 'TXN_PLACEHOLDER',
            })

        except Exception as e:
            logger.error(f"Payment processing error: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': f'Payment failed: {str(e)}'
            }, status=400)


class BillingSettingsView(LoginRequiredMixin, TemplateView):
    """
    Manage billing settings
    """
    template_name = 'company/billing/settings.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = getattr(self.request.user, 'company', None)

        if company:
            context['company'] = company
            context['billing_email'] = company.billing_email or company.email
            context['billing_address'] = company.physical_address

        return context

    def post(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        # Update billing settings — validate email format before persisting
        billing_email = request.POST.get('billing_email', '').strip()
        if billing_email:
            if '@' not in billing_email or '.' not in billing_email.split('@')[-1]:
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid email address format'
                }, status=400)
            company.billing_email = billing_email
            company.save(update_fields=['billing_email'])

        return JsonResponse({
            'success': True,
            'message': 'Billing settings updated successfully'
        })


class ExportInvoicesView(LoginRequiredMixin, View):
    """
    Export invoices as CSV
    """

    def get(self, request, *args, **kwargs):
        import csv

        company = getattr(request.user, 'company', None)
        if not company:
            raise Http404("No company found")

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="invoices_{company.company_id}.csv"'

        writer = csv.writer(response)
        writer.writerow(['Invoice ID', 'Date', 'Amount', 'Status', 'Description'])

        # TODO: Export actual invoices
        # invoices = Invoice.objects.filter(company=company).order_by('-date')
        # for invoice in invoices:
        #     writer.writerow([
        #         invoice.invoice_number,
        #         invoice.date.strftime('%Y-%m-%d'),
        #         invoice.amount,
        #         invoice.status,
        #         invoice.description,
        #     ])

        # Placeholder
        if company.last_payment_date and company.plan:
            writer.writerow([
                f'INV-{company.company_id}-001',
                company.last_payment_date.strftime('%Y-%m-%d'),
                company.plan.price,
                'PAID',
                f'{company.plan.display_name} Subscription',
            ])

        return response


# =============================================================================
# Invoice Model (Create this in models.py)
# =============================================================================
"""
class Invoice(models.Model):
    '''Invoice model for billing history'''

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]

    company = models.ForeignKey(
        'Company',
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    invoice_number = models.CharField(max_length=50, unique=True)
    date = models.DateField(default=timezone.now)
    due_date = models.DateField()

    # Amounts
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    # Payment info
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    payment_method = models.CharField(max_length=50, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # Details
    description = models.TextField()
    notes = models.TextField(blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['invoice_number']),
        ]

    def __str__(self):
        return f"{self.invoice_number} - {self.company.name}"

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self.generate_invoice_number()
        super().save(*args, **kwargs)

    def generate_invoice_number(self):
        '''Generate unique invoice number'''
        import uuid
        year = timezone.now().year
        short_uuid = str(uuid.uuid4())[:8].upper()
        return f"INV-{year}-{short_uuid}"


class InvoiceItem(models.Model):
    '''Line items for invoices'''

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='items'
    )
    description = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.description} - {self.invoice.invoice_number}"

    def save(self, *args, **kwargs):
        self.total = self.quantity * self.unit_price
        super().save(*args, **kwargs)
"""