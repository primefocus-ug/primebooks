from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db.models import Sum, Q
from decimal import Decimal, ROUND_HALF_UP
import uuid
from .efris import EFRISInvoiceMixin



class Invoice(models.Model,EFRISInvoiceMixin):
    STATUS_CHOICES = [
        ('DRAFT', _('Draft')),
        ('SENT', _('Sent')),
        ('PAID', _('Paid')),
        ('CANCELLED', _('Cancelled')),
        ('REFUNDED', _('Refunded')),
        ('PARTIALLY_PAID', _('Partially Paid')),
    ]

    DOCUMENT_TYPES = [
        ('INVOICE', _('Invoice')),
        ('CREDIT_NOTE', _('Credit Note')),
        ('DEBIT_NOTE', _('Debit Note')),
        ('PROFORMA', _('Proforma Invoice')),
    ]

    # EFRIS Document Types
    EFRIS_DOCUMENT_TYPES = [
        ('1', 'Normal Invoice'),
        ('2', 'Credit Note'),
        ('3', 'Debit Note'),
        ('4', 'Proforma Invoice'),
    ]

    # EFRIS Business Types
    BUSINESS_TYPES = [
        ('B2C', 'Business to Consumer'),
        ('B2B', 'Business to Business'),
        ('B2G', 'Business to Government'),
    ]

    # EFRIS Fiscalization Status
    EFRIS_STATUS_CHOICES = [
        ('pending', 'Pending Fiscalization'),
        ('fiscalized', 'Fiscalized'),
        ('failed', 'Fiscalization Failed'),
        ('cancelled', 'Cancelled'),
    ]

    # Basic Invoice Information
    invoice_number = models.CharField(
        max_length=50,
        verbose_name=_("Invoice Number"),
        db_index=True
    )

    sale = models.OneToOneField(
        'sales.Sale',
        on_delete=models.PROTECT,
        related_name='invoice',
        verbose_name=_("Sale")
    )

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='invoices',
        verbose_name=_("Store")
    )
    fiscalization_error = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Fiscalization Error"),
        help_text=_("Error message if fiscalization failed")
    )


    efris_status = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_("EFRIS Status"),
        help_text=_("Current status from EFRIS system")
    )
    # Dates
    issue_date = models.DateField(default=timezone.now, verbose_name=_("Issue Date"))
    due_date = models.DateField(verbose_name=_("Due Date"))

    # Status and Document Type
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES, default='INVOICE')

    # EFRIS Integration Fields
    efris_document_type = models.CharField(
        max_length=2,
        choices=EFRIS_DOCUMENT_TYPES,
        default='1',
        verbose_name=_("EFRIS Document Type")
    )

    business_type = models.CharField(
        max_length=3,
        choices=BUSINESS_TYPES,
        blank=True,
        verbose_name=_("Business Type")
    )

    # Financial Information
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )

    # EFRIS Fiscalization Details
    fiscal_document_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Fiscal Document Number"),
        db_index=True
    )
    fiscal_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True
    )
    verification_code = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Verification Code")
    )
    qr_code = models.TextField(
        blank=True,
        verbose_name=_("QR Code Data")
    )

    currency_code = models.CharField(max_length=3, default='UGX', verbose_name=_("Currency"))
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=1,
        verbose_name=_("Exchange Rate to UGX")
    )

    ugx_subtotal = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        verbose_name=_("UGX Subtotal")
    )
    ugx_tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        verbose_name=_("UGX Tax Amount")
    )
    ugx_total_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        verbose_name=_("UGX Total Amount")
    )

    device_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Device Number")
    )
    operator_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Operator Name")
    )

    fiscalization_status = models.CharField(
        max_length=15,
        choices=EFRIS_STATUS_CHOICES,
        default='pending',
        verbose_name=_("Fiscalization Status"),
        db_index=True
    )


    is_fiscalized = models.BooleanField(default=False, db_index=True)
    fiscalization_time = models.DateTimeField(blank=True, null=True)
    fiscalized_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fiscalized_invoices'
    )

    original_fdn = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Original FDN"),
        help_text=_("For credit/debit notes")
    )

    requires_ura_approval = models.BooleanField(
        default=False,
        verbose_name=_("Requires URA Approval")
    )
    ura_approved = models.BooleanField(
        default=False,
        verbose_name=_("URA Approved")
    )
    ura_approval_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("URA Approval Date")
    )

    auto_fiscalize = models.BooleanField(
        default=True,
        verbose_name=_("Auto-Fiscalize"),
        help_text=_("Automatically fiscalize when invoice is sent")
    )

    notes = models.TextField(blank=True, null=True)
    terms = models.TextField(blank=True, null=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_invoices'
    )
    related_invoice = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = _("Invoice")
        verbose_name_plural = _("Invoices")
        ordering = ['-issue_date']
        indexes = [
            models.Index(fields=['invoice_number']),
            models.Index(fields=['fiscal_document_number']),
            models.Index(fields=['fiscal_number']),
            models.Index(fields=['is_fiscalized']),
            models.Index(fields=['fiscalization_status']),
            models.Index(fields=['business_type']),
            models.Index(fields=['efris_document_type']),
            models.Index(fields=['store', 'issue_date']),
            models.Index(fields=['status', 'due_date']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['invoice_number'],
                name='unique_invoice_number_per_tenant'
            ),
            models.UniqueConstraint(
                fields=['fiscal_document_number'],
                condition=Q(fiscal_document_number__isnull=False) & ~Q(fiscal_document_number=''),
                name='unique_fiscal_document_number_per_tenant'
            ),
            models.UniqueConstraint(
                fields=['fiscal_number'],
                condition=Q(fiscal_number__isnull=False) & ~Q(fiscal_number=''),
                name='unique_fiscal_number_per_tenant'
            )
        ]
        permissions = [
            ('fiscalize_invoice', 'Can fiscalize invoices with EFRIS'),
            ('manage_credit_notes', 'Can create and manage credit notes'),
        ]

    def clean(self):
        """Model-level validation"""
        super().clean()

        if self.fiscalization_status == 'fiscalized' and not self.fiscal_document_number:
            raise ValidationError("Fiscal document number is required for fiscalized invoices")

        if self.efris_document_type in ['2', '3'] and not self.original_fdn:
            raise ValidationError("Original FDN is required for credit/debit notes")

        subtotal = Decimal(self.subtotal or 0)
        tax = Decimal(self.tax_amount or 0)
        discount = Decimal(self.discount_amount or 0)
        total = Decimal(self.total_amount or 0)

        # ========== FIXED: Tax-inclusive validation ==========
        # For tax-inclusive prices: total = subtotal - discount
        # Tax is already included in subtotal
        calculated_total = subtotal - discount
        # =====================================================

        if abs(total - calculated_total) > Decimal('0.01'):
            raise ValidationError(
                f"Total amount doesn't match calculated total. "
                f"Expected: {calculated_total}, Got: {total}, "
                f"Subtotal: {subtotal}, Tax: {tax}, Discount: {discount}"
            )

    def save(self, *args, **kwargs):
        # Auto-populate store from sale
        if not self.store and self.sale and hasattr(self.sale, 'store'):
            self.store = self.sale.store

        # Auto-generate invoice number
        if not self.invoice_number:
            self.invoice_number = self.generate_invoice_number()

        # Auto-set due date
        if not self.due_date:
            self.due_date = self.issue_date + timezone.timedelta(days=30)

        # Auto-populate business type if not set
        if not self.business_type:
            self.business_type = self._determine_business_type()

        # Auto-populate operator name
        if not self.operator_name and self.created_by:
            self.operator_name = self.created_by.get_full_name() or str(self.created_by)

        # Calculate UGX amounts for EFRIS
        self.ugx_subtotal = (self.subtotal * self.exchange_rate).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        self.ugx_tax_amount = (self.tax_amount * self.exchange_rate).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        self.ugx_total_amount = (self.total_amount * self.exchange_rate).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        # Sync fiscalization fields for backward compatibility
        if self.fiscalization_status == 'fiscalized':
            self.is_fiscalized = True
            if not self.fiscalization_time:
                self.fiscalization_time = timezone.now()
            # Sync fiscal_number with fiscal_document_number
            if self.fiscal_document_number and not self.fiscal_number:
                self.fiscal_number = self.fiscal_document_number
        else:
            self.is_fiscalized = False

        # ========== FIXED: Skip validation when only updating specific fields ==========
        # Only run full validation if we're creating a new invoice or updating all fields
        update_fields = kwargs.get('update_fields')

        # If update_fields is specified and contains only fiscalization-related fields,
        # skip full_clean to avoid validation errors
        fiscalization_fields = {
            'fiscal_document_number', 'fiscal_number', 'verification_code',
            'qr_code', 'fiscalization_status', 'is_fiscalized',
            'fiscalization_time', 'fiscalized_by', 'fiscalization_error',
            'efris_status'
        }

        should_validate = True
        if update_fields:
            # Check if we're only updating fiscalization fields
            updating_fields = set(update_fields)
            if updating_fields.issubset(fiscalization_fields):
                should_validate = False

        # Run model validation only when necessary
        if should_validate:
            self.full_clean()
        # ================================================================================

        super().save(*args, **kwargs)

    def generate_invoice_number(self):
        """Generate unique invoice number based on document type"""
        prefix = {
            'INVOICE': 'INV',
            'CREDIT_NOTE': 'CN',
            'DEBIT_NOTE': 'DN',
            'PROFORMA': 'PRO'
        }.get(self.document_type, 'INV')

        last_invoice = Invoice.objects.filter(
            document_type=self.document_type,
            issue_date__year=timezone.now().year
        ).order_by('-created_at').first()

        if last_invoice and last_invoice.invoice_number:
            try:
                parts = last_invoice.invoice_number.split('-')
                sequence = int(parts[-1]) + 1 if len(parts) >= 3 else 1
            except (ValueError, IndexError):
                sequence = 1
        else:
            sequence = 1

        return f"{prefix}-{timezone.now().strftime('%Y%m%d')}-{sequence:04d}"

    def _determine_business_type(self):
        """Determine business type from sale customer"""
        if self.sale and self.sale.customer:
            # Check if customer has EFRIS customer profile
            efris_customer = getattr(self.sale.customer, 'efris_customer', None)
            if efris_customer:
                return efris_customer.get_business_type()

            # Fallback logic based on customer attributes
            if hasattr(self.sale.customer, 'customer_type'):
                if self.sale.customer.customer_type == 'GOVERNMENT':
                    return 'B2G'
                elif self.sale.customer.customer_type == 'BUSINESS' and getattr(self.sale.customer, 'tin', None):
                    return 'B2B'

        return 'B2C'

    @property
    def days_overdue(self):
        """Calculate days overdue"""
        if self.status in ['PAID', 'CANCELLED']:
            return 0
        return max(0, (timezone.now().date() - self.due_date).days)

    @property
    def amount_paid(self):
        """Total amount paid for this invoice"""
        return self.payments.aggregate(total=Sum('amount'))['total'] or 0

    @property
    def amount_outstanding(self):
        """Outstanding amount to be paid"""
        return max(0, self.total_amount - self.amount_paid)

    @property
    def is_overdue(self):
        """Check if invoice is overdue"""
        return self.days_overdue > 0 and self.status not in ['PAID', 'CANCELLED']

    @property
    def can_fiscalize_status(self):
        """Check if invoice can be fiscalized (EFRIS compatible)"""
        return self.fiscalization_status == 'pending'

    @property
    def efris_is_fiscalized(self):
        """Check if invoice is fiscalized (EFRIS compatible)"""
        return self.fiscalization_status == 'fiscalized'

    @property
    def customer(self):
        """Get customer from related sale"""
        if self.sale and self.sale.customer:
            return self.sale.customer
        return None
    def update_status(self):
        """Update invoice status based on payments"""
        if self.status in ['CANCELLED', 'REFUNDED']:
            return

        paid_amount = self.amount_paid
        if paid_amount >= self.total_amount:
            self.status = 'PAID'
        elif paid_amount > 0:
            self.status = 'PARTIALLY_PAID'
        elif self.status == 'DRAFT':
            pass
        else:
            self.status = 'SENT'

        self.save(update_fields=['status'])

    def fiscalize(self, user=None):
        """Fiscalize invoice with EFRIS"""
        can_fiscalize, message = self.can_fiscalize(user)
        if not can_fiscalize:
            raise ValidationError(message)

        # Generate EFRIS fiscal document number
        self.fiscal_document_number = f"EFRIS-{uuid.uuid4().hex[:10].upper()}"
        self.fiscal_number = self.fiscal_document_number  # Backward compatibility
        self.verification_code = uuid.uuid4().hex
        self.fiscalization_status = 'fiscalized'
        self.is_fiscalized = True
        self.fiscalization_time = timezone.now()
        self.fiscalized_by = user

        self.save(update_fields=[
            'fiscal_document_number', 'fiscal_number', 'verification_code',
            'fiscalization_status', 'is_fiscalized', 'fiscalization_time', 'fiscalized_by'
        ])

        return True

    def mark_fiscalization_failed(self, reason=None):
        """Mark fiscalization as failed"""
        self.fiscalization_status = 'failed'
        self.is_fiscalized = False
        if reason:
            self.notes = f"{self.notes or ''}\nFiscalization failed: {reason}".strip()
        self.save(update_fields=['fiscalization_status', 'is_fiscalized', 'notes'])

    def approve_ura_credit_note(self, approved_by=None):
        """Approve URA credit/debit note"""
        if self.document_type not in ['CREDIT_NOTE', 'DEBIT_NOTE']:
            raise ValidationError("URA approval only applies to credit/debit notes")

        if self.business_type not in ['B2B', 'B2G']:
            raise ValidationError("URA approval only required for B2B/B2G transactions")

        self.ura_approved = True
        self.ura_approval_date = timezone.now()
        self.save(update_fields=['ura_approved', 'ura_approval_date'])

    def __str__(self):
        return f"{self.get_document_type_display()} #{self.invoice_number}"

    def update_from_efris_response(self, efris_data):
        """Update invoice with EFRIS fiscalization response data"""
        try:
            basic_info = efris_data.get('basicInformation', {})
            summary = efris_data.get('summary', {})

            updates = []

            # Fiscal document number
            invoice_no = basic_info.get('invoiceNo') or efris_data.get('invoice_no')
            if invoice_no:
                self.fiscal_document_number = invoice_no
                self.fiscal_number = invoice_no  # keep in sync
                updates.extend(['fiscal_document_number', 'fiscal_number'])

            # Verification code
            verification_code = (
                    basic_info.get('antifakeCode') or
                    efris_data.get('verification_code') or
                    efris_data.get('fiscal_code')
            )
            if verification_code:
                self.verification_code = verification_code
                updates.append('verification_code')

            # QR code
            qr_code = (
                    summary.get('qrCode')
                    or summary.get('qr_code')
                    or efris_data.get('qrCode')
                    or efris_data.get('qr_code')
                    or efris_data.get('full_response', {}).get('summary', {}).get('qrCode')
            )
            if qr_code:
                self.qr_code = qr_code
                updates.append('qr_code')

            # Optional IDs
            if 'invoice_id' in efris_data:
                self.efris_invoice_id = efris_data['invoice_id']
                updates.append('efris_invoice_id')
            if 'fiscal_code' in efris_data:
                self.fiscal_code = efris_data['fiscal_code']
                updates.append('fiscal_code')

            # Fiscalization metadata
            self.fiscalization_status = 'fiscalized'
            self.is_fiscalized = True
            self.fiscalization_time = timezone.now()
            updates.extend(['fiscalization_status', 'is_fiscalized', 'fiscalization_time'])

            # Save invoice updates
            if updates:
                self.save(update_fields=updates)

            # Propagate to sale
            self.update_sale_from_efris()

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update invoice {self.id} from EFRIS response: {e}", exc_info=True)
            raise

    def update_sale_from_efris(self):
        """Update related sale with EFRIS fiscalization data"""
        if not getattr(self, "sale", None):
            return

        try:
            sale_updates = []

            if self.fiscal_document_number:
                self.sale.efris_invoice_number = self.fiscal_document_number
                sale_updates.append('efris_invoice_number')

            if self.verification_code:
                self.sale.verification_code = self.verification_code
                sale_updates.append('verification_code')

            if self.qr_code:
                self.sale.qr_code = self.qr_code
                sale_updates.append('qr_code')

            if self.is_fiscalized:
                self.sale.is_fiscalized = True
                self.sale.fiscalization_time = self.fiscalization_time
                sale_updates.extend(['is_fiscalized', 'fiscalization_time'])

            if sale_updates:
                self.sale.save(update_fields=sale_updates)

                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Sale {self.sale.id} updated with fiscalization fields: {sale_updates}")

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update sale {self.sale.id} from invoice fiscalization: {e}", exc_info=True)

    def get_efris_invoice_data(self):
        """Get complete invoice data formatted for EFRIS API"""
        if not self.sale:
            raise ValueError("Invoice must have an associated sale for EFRIS processing")

        # Use Sale's EFRIS mixin methods to build data
        seller_details = self.sale.store.company.get_efris_seller_details() if hasattr(self.sale.store.company,
                                                                                       'get_efris_seller_details') else self._get_default_seller_details()

        buyer_details = {}
        if self.sale.customer and hasattr(self.sale.customer, 'get_efris_buyer_details'):
            buyer_details = self.sale.customer.get_efris_buyer_details()
        else:
            buyer_details = self._get_default_buyer_details()

        basic_info = self.sale.get_efris_basic_info() if hasattr(self.sale,
                                                                 'get_efris_basic_info') else self._get_default_basic_info()
        goods_details = self.sale.get_efris_goods_details() if hasattr(self.sale, 'get_efris_goods_details') else []
        summary = self.sale.get_efris_summary() if hasattr(self.sale,
                                                           'get_efris_summary') else self._get_default_summary()
        payment_details = self.sale.get_efris_payment_details() if hasattr(self.sale,
                                                                           'get_efris_payment_details') else []

        # Build tax details
        tax_details = self._build_tax_details()

        return {
            "sellerDetails": seller_details,
            "basicInformation": basic_info,
            "buyerDetails": buyer_details,
            "goodsDetails": goods_details,
            "taxDetails": tax_details,
            "summary": summary,
            "payWay": payment_details if payment_details else None
        }

    def _get_default_seller_details(self):
        """Fallback seller details if company doesn't have EFRIS mixin"""
        company = self.sale.store.company
        return {
            "tin": getattr(company, 'tin', ''),
            "ninBrn": getattr(company, 'brn', '') or getattr(company, 'nin', ''),
            "legalName": getattr(company, 'name', ''),
            "businessName": getattr(company, 'trading_name', '') or getattr(company, 'name', ''),
            "address": getattr(company, 'physical_address', ''),
            "mobilePhone": getattr(company, 'phone', ''),
            "emailAddress": getattr(company, 'email', ''),
        }

    def _get_default_buyer_details(self):
        """Fallback buyer details if customer doesn't have EFRIS mixin"""
        # ========== FIXED: Get customer from sale ==========
        customer = self.sale.customer if self.sale else None

        if not customer:
            return {
                "buyerType": "1",  # B2C
                "buyerLegalName": "Walk-in Customer",
                "buyerAddress": "",
                "buyerEmail": "",
                "buyerMobilePhone": "",
                "buyerTin": "",
                "buyerNinBrn": ""
            }
        # ===================================================

        # Determine buyer type
        buyer_type = "1"  # B2C default
        if hasattr(customer, 'customer_type') and customer.customer_type:
            if customer.customer_type.upper() == 'BUSINESS':
                buyer_type = "0"  # B2B
            elif customer.customer_type.upper() in ['GOVERNMENT', 'PUBLIC']:
                buyer_type = "3"  # B2G
        elif getattr(customer, 'tin', None):
            buyer_type = "0"  # B2B if has TIN

        return {
            "buyerType": buyer_type,
            "buyerTin": getattr(customer, 'tin', '') or '',
            "buyerNinBrn": getattr(customer, 'nin', '') or getattr(customer, 'brn', '') or '',
            "buyerLegalName": customer.name or 'Unknown Customer',
            "buyerEmail": getattr(customer, 'email', '') or '',
            "buyerMobilePhone": getattr(customer, 'phone', '') or '',
            "buyerAddress": getattr(customer, 'physical_address', '') or getattr(customer, 'postal_address', '') or ''
        }

    def _get_default_basic_info(self):
        """Fallback basic info if sale doesn't have EFRIS mixin"""
        return {
            "invoiceNo": "",  # Will be assigned by EFRIS
            "issuedDate": self.issue_date.strftime('%Y-%m-%d %H:%M:%S'),
            "operator": self.operator_name or 'System',
            "currency": self.currency_code or 'UGX',
            "invoiceType": "1",
            "invoiceKind": self.efris_document_type or "1",
        }

    def _get_default_summary(self):
        """Fallback summary if sale doesn't have EFRIS mixin"""
        net_amount = self.subtotal - (self.discount_amount or 0)
        return {
            "netAmount": str(net_amount),
            "taxAmount": str(self.tax_amount or 0),
            "grossAmount": str(self.total_amount),
            "itemCount": "1",  # Default
            "modeCode": "1",
            "remarks": self.notes or "Invoice generated via system"
        }

    def _build_tax_details(self):
        """Build tax details for EFRIS"""
        net_amount = self.subtotal - (self.discount_amount or 0)
        tax_details = []

        if self.tax_amount and self.tax_amount > 0:
            tax_details.append({
                "taxCategoryCode": "01",  # Standard VAT
                "netAmount": str(net_amount),
                "taxRate": "0.18",  # 18% VAT
                "taxAmount": str(self.tax_amount),
                "grossAmount": str(self.total_amount),
                "taxRateName": "Standard Rate (18%)"
            })
        else:
            tax_details.append({
                "taxCategoryCode": "02",  # Zero rate
                "netAmount": str(net_amount),
                "taxRate": "0.00",
                "taxAmount": "0",
                "grossAmount": str(self.total_amount),
                "taxRateName": "Zero Rate (0%)"
            })

        return tax_details

    def can_fiscalize(self, user=None):
        """Enhanced fiscalization validation"""
        if self.fiscalization_status == 'fiscalized':
            return False, "Invoice is already fiscalized"

        if self.status not in ['SENT', 'PAID', 'PARTIALLY_PAID']:
            return False, "Only sent or paid invoices can be fiscalized"

        # Check company EFRIS configuration
        if not self.sale or not self.sale.store:
            return False, "Invoice must be associated with a store"

        company = self.sale.store.company
        if not getattr(company, 'efris_enabled', False):
            return False, "EFRIS is not enabled for this company"

        # Check if sale can be fiscalized
        if hasattr(self.sale, 'can_fiscalize'):
            sale_can_fiscalize, sale_reason = self.sale.can_fiscalize(user)
            if not sale_can_fiscalize:
                return False, f"Related sale cannot be fiscalized: {sale_reason}"

        # Check for required EFRIS data
        if not self.total_amount or self.total_amount <= 0:
            return False, "Invoice must have a positive total amount"

        # Document type specific checks
        if self.document_type in ['CREDIT_NOTE', 'DEBIT_NOTE']:
            if self.business_type in ['B2B', 'B2G'] and not self.ura_approved:
                return False, "URA approval required for B2B/B2G credit/debit notes"

            if not self.original_fdn:
                return False, "Original fiscal document number required for credit/debit notes"

        return True, "Invoice can be fiscalized"


class InvoiceTemplate(models.Model):
    name = models.CharField(max_length=100, verbose_name=_("Template Name"))
    template_file = models.FileField(
        upload_to='invoice_templates/',
        verbose_name=_("Template File")
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name=_("Is Default Template")
    )
    is_efris_compliant = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Compliant"),
        help_text=_("Whether this template meets URA requirements")
    )
    version = models.CharField(
        max_length=20,
        default='1.0',
        verbose_name=_("Version")
    )
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_templates',
        verbose_name=_("Created By")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At")
    )

    class Meta:
        verbose_name = _("Invoice Template")
        verbose_name_plural = _("Invoice Templates")
        ordering = ['-is_default', 'name']

    def __str__(self):
        return f"{self.name} (v{self.version})"


class InvoicePayment(models.Model):
    PAYMENT_METHODS = [
        ('CASH', _('Cash')),
        ('BANK_TRANSFER', _('Bank Transfer')),
        ('MOBILE_MONEY', _('Mobile Money')),
        ('CHEQUE', _('Cheque')),
        ('CREDIT_CARD', _('Credit Card')),
        ('OTHER', _('Other')),
    ]

    invoice = models.ForeignKey(
        'Invoice',
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name=_("Invoice")
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
        verbose_name=_("Amount")
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHODS,
        verbose_name=_("Payment Method")
    )
    transaction_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Transaction Reference")
    )
    payment_date = models.DateField(
        default=timezone.now,
        verbose_name=_("Payment Date")
    )
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Notes")
    )
    processed_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_payments',
        verbose_name=_("Processed By")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )

    class Meta:
        verbose_name = _("Invoice Payment")
        verbose_name_plural = _("Invoice Payments")
        ordering = ['-payment_date']

    def clean(self):
        """Validate payment amount does not exceed outstanding amount"""
        super().clean()
        if self.invoice:
            outstanding = self.invoice.amount_outstanding
            if self.pk:  # Include previous payment amount if updating
                current_payment = InvoicePayment.objects.filter(pk=self.pk).first()
                if current_payment:
                    outstanding += current_payment.amount

            if self.amount > outstanding:
                raise ValidationError({
                    'amount': _('Payment amount cannot exceed outstanding invoice amount')
                })

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
        self.invoice.update_status()

    def delete(self, *args, **kwargs):
        invoice = self.invoice
        super().delete(*args, **kwargs)
        invoice.update_status()

    def __str__(self):
        return f"Payment of {self.amount} for {self.invoice.invoice_number}"


class FiscalizationAudit(models.Model):
    ACTION_CHOICES = [
        ('FISCALIZE', _('Fiscalized')),
        ('RETRY', _('Retry Fiscalization')),
        ('ERROR', _('Fiscalization Error')),
        ('URA_APPROVAL', _('URA Approval')),
        ('EFRIS_SUBMIT', _('EFRIS Submission')),
    ]

    invoice = models.ForeignKey(
        'Invoice',
        on_delete=models.CASCADE,
        related_name='fiscalization_audits'
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    success = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, null=True)
    efris_response = models.JSONField(default=dict, blank=True)

    # Additional EFRIS audit fields
    fiscal_document_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Fiscal Document Number")
    )
    verification_code = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Verification Code")
    )
    device_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Device Number")
    )

    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = _('Fiscalization Audit')
        verbose_name_plural = _('Fiscalization Audits')

    def __str__(self):
        return f"{self.action} - {self.invoice.invoice_number}"