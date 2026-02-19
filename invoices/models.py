from datetime import timedelta

from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db.models import Sum, Q
from decimal import Decimal, ROUND_HALF_UP
import uuid
import logging

from inventory.models import Stock
from .efris import EFRISInvoiceMixin
from django.db import transaction

logger = logging.getLogger(__name__)

class Invoice(models.Model, EFRISInvoiceMixin):
    """Invoice detail model - stores invoice-specific data"""


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

    sale = models.OneToOneField(
        'sales.Sale',
        on_delete=models.CASCADE,  # Changed from PROTECT
        related_name='invoice_detail',
        verbose_name=_("Sale")
    )

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='invoice_details',
        verbose_name=_("Store")
    )


    terms = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Terms and Conditions")
    )

    purchase_order = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Purchase Order Number")
    )

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
    # EFRIS Export Fields
    export_status = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        db_index=True,
        help_text="EFRIS export status: 101=Processing, 102=Cleared"
    )
    export_delivery_terms = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Incoterms: FOB, CIF, CFR, etc."
    )
    export_total_weight = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Total gross weight in KGM"
    )
    export_sad_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Customs SAD declaration number (20 digits)"
    )
    export_sad_submitted_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the SAD was submitted"
    )
    export_cleared_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When customs clearance was completed"
    )
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_invoice_details'
    )

    related_invoice = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = _("Invoice Detail")
        verbose_name_plural = _("Invoice Details")
        ordering = ['-created_at']

        indexes = [
            models.Index(fields=['sale']),
            models.Index(fields=['fiscal_document_number']),
            models.Index(fields=['fiscal_number']),
            models.Index(fields=['is_fiscalized']),
            models.Index(fields=['fiscalization_status']),
            models.Index(fields=['business_type']),
            models.Index(fields=['efris_document_type']),
            models.Index(fields=['export_status']),
        ]

        constraints = [
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

    def __str__(self):
        return f"Invoice Detail for {self.sale.document_number}"

    def clean(self):
        """Validate invoice data"""
        super().clean()

        if self.sale and self.sale.is_voided:
            raise ValidationError("Cannot create invoice for a voided sale")

        if self.efris_document_type in ['2', '3'] and not self.original_fdn:
            raise ValidationError({
                'original_fdn': _('Original Fiscal Document Number is required for credit/debit notes')
            })

    def validate_export_fields(self):
        """Validate export invoice fields"""
        errors = []

        if not self.sale.is_export_sale:
            return errors

        # Validate delivery terms synced from sale
        if not self.export_delivery_terms and not self.sale.delivery_terms_code:
            errors.append("Delivery terms required for export invoice")

        # Validate total weight calculated
        if not self.export_total_weight or self.export_total_weight <= 0:
            errors.append("Total weight required for export invoice")

        return errors

    def sync_export_fields_from_sale(self):
        """Sync export fields from sale"""
        if self.sale and self.sale.is_export_sale:
            self.export_delivery_terms = self.sale.delivery_terms_code
            # Calculate total weight from items
            total_weight = sum(
                item.export_total_weight or 0
                for item in self.sale.items.filter(item_type='PRODUCT')
            )
            self.export_total_weight = total_weight
            self.save(update_fields=['export_delivery_terms', 'export_total_weight'])

    def save(self, *args, **kwargs):
        # Auto-populate store from sale
        if not self.store and self.sale and hasattr(self.sale, 'store'):
            self.store = self.sale.store

        # Auto-populate operator name
        if not self.operator_name and self.sale.created_by:
            self.operator_name = self.sale.created_by.get_full_name() or str(self.sale.created_by)

        # Auto-populate business type if not set
        if not self.business_type:
            self.business_type = self._determine_business_type()

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

        # Skip validation when only updating specific fields
        update_fields = kwargs.get('update_fields')
        fiscalization_fields = {
            'fiscal_document_number', 'fiscal_number', 'verification_code',
            'qr_code', 'fiscalization_status', 'is_fiscalized',
            'fiscalization_time', 'fiscalized_by', 'fiscalization_error',
            'efris_status'
        }

        should_validate = True
        if update_fields:
            updating_fields = set(update_fields)
            if updating_fields.issubset(fiscalization_fields):
                should_validate = False

        # Run model validation only when necessary
        if should_validate:
            self.full_clean()

        super().save(*args, **kwargs)

        if not self.pk and self.sale.customer and self.sale.document_type == 'INVOICE':
            self._create_credit_statement_entry()

    def _create_credit_statement_entry(self):
        """Create credit statement entry when invoice is created"""
        from customers.models import CustomerCreditStatement

        customer = self.sale.customer
        balance_before = customer.credit_balance
        balance_after = balance_before + self.total_amount

        CustomerCreditStatement.objects.create(
            customer=customer,
            transaction_type='INVOICE',
            sale=self.sale,
            amount=self.total_amount,
            balance_before=balance_before,
            balance_after=balance_after,
            description=f"Invoice {self.sale.document_number} created",
            reference_number=self.sale.document_number,
            created_by=self.sale.created_by
        )

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


    def can_mark_as_paid(self):
        """Check if invoice can be marked as paid (sufficient stock)"""
        if self.sale.status in ['PAID', 'COMPLETED']:
            return False, "Invoice is already paid"

        if self.sale.is_voided:
            return False, "Cannot mark voided sale as paid"

        # Check stock availability for all product items
        for item in self.sale.items.filter(item_type='PRODUCT'):
            stock = Stock.objects.filter(
                product=item.product,
                store=self.sale.store
            ).first()

            if not stock or stock.quantity < item.quantity:
                available = stock.quantity if stock else 0
                return False, f"Insufficient stock for {item.product.name}. Available: {available}, Required: {item.quantity}"

        return True, "Can mark as paid"

    def mark_as_paid(self, user=None, payment_method='CASH', transaction_reference=None):
        """Mark invoice as paid and trigger stock movement"""
        can_pay, message = self.can_mark_as_paid()
        if not can_pay:
            raise ValidationError(message)

        with transaction.atomic():
            # Update invoice status
            old_status = self.sale.status

            # Update sale status to trigger stock deduction
            self.sale.status = 'PAID'
            self.sale.payment_status = 'PAID'
            self.sale.payment_method = payment_method
            self.sale.save(update_fields=['status', 'payment_status', 'payment_method'])

            # Create payment record
            from sales.models import Payment
            Payment.objects.create(
                sale=self.sale,
                store=self.sale.store,
                amount=self.sale.total_amount,
                payment_method=payment_method,
                transaction_reference=transaction_reference,
                is_confirmed=True,
                confirmed_at=timezone.now(),
                created_by=user,
                payment_type='FULL',
                notes=f"Invoice payment - Status changed from {old_status} to PAID"
            )

            # If sale status changed from PENDING to PAID, items need stock deduction
            if old_status in ['DRAFT', 'PENDING_PAYMENT']:
                for item in self.sale.items.filter(item_type='PRODUCT'):
                    # Manually trigger stock deduction since item already exists
                    if not hasattr(item, '_stock_deducted'):
                        item.deduct_stock()
                        item._stock_deducted = True

            logger.info(f"Invoice {self.id} marked as paid by {user}, stock deducted")

            return True

    def can_edit(self):
        """Check if invoice can be edited"""
        if self.sale.status in ['PAID', 'COMPLETED']:
            return False, "Cannot edit paid invoice"

        if self.sale.is_voided:
            return False, "Cannot edit voided invoice"

        if self.is_fiscalized:
            return False, "Cannot edit fiscalized invoice"

        return True, "Can edit invoice"

    def can_cancel(self):
        """Check if invoice can be cancelled"""
        if self.sale.status in ['PAID', 'COMPLETED']:
            return False, "Cannot cancel paid invoice. Use refund instead."

        if self.sale.is_voided:
            return False, "Invoice is already cancelled"

        return True, "Can cancel invoice"

    def cancel_invoice(self, reason, user=None):
        """Cancel/void an unpaid invoice"""
        can_cancel, message = self.can_cancel()
        if not can_cancel:
            raise ValidationError(message)

        with transaction.atomic():
            self.sale.void_sale(reason)
            self.sale.status = 'CANCELLED'
            self.sale.save(update_fields=['status'])

            logger.info(f"Invoice {self.id} cancelled by {user}. Reason: {reason}")

            return True

    @property
    def can_send(self):
        """Check if invoice can be sent"""
        return self.sale.status == 'DRAFT'

    def mark_as_sent(self, user=None):
        """Mark invoice as sent to customer"""
        if not self.can_send:
            raise ValidationError("Invoice cannot be sent in current status")

        self.sale.status = 'PENDING_PAYMENT'
        self.sale.save(update_fields=['status'])

        logger.info(f"Invoice {self.id} marked as sent by {user}")
        return True

    @property
    def stock_availability(self):
        """Get stock availability for all items"""
        availability = []
        for item in self.sale.items.filter(item_type='PRODUCT'):
            stock = Stock.objects.filter(
                product=item.product,
                store=self.sale.store
            ).first()

            available_qty = stock.quantity if stock else 0
            availability.append({
                'product': item.product,
                'required': item.quantity,
                'available': available_qty,
                'sufficient': available_qty >= item.quantity
            })

        return availability

    @property
    def invoice_number(self):
        """Get invoice number from related sale"""
        return self.sale.document_number if self.sale else None

    @property
    def issue_date(self):
        return self.sale.created_at.date() if self.sale else None

    @property
    def due_date(self):
        """Get due date from related sale"""
        return self.sale.due_date if self.sale else None

    @property
    def subtotal(self):
        """Get subtotal from related sale"""
        return self.sale.subtotal if self.sale else Decimal('0')

    @property
    def tax_amount(self):
        """Get tax amount from related sale"""
        return self.sale.tax_amount if self.sale else Decimal('0')

    @property
    def discount_amount(self):
        """Get discount amount from related sale"""
        return self.sale.discount_amount if self.sale else Decimal('0')

    @property
    def total_amount(self):
        """Get total amount from related sale"""
        return self.sale.total_amount if self.sale else Decimal('0')

    @property
    def currency_code(self):
        """Get currency from related sale"""
        return self.sale.currency if self.sale else 'UGX'

    @property
    def customer(self):
        """Get customer from related sale"""
        return self.sale.customer if self.sale else None

    @property
    def days_overdue(self):
        """Calculate days overdue from related sale"""
        return self.sale.days_overdue if self.sale else 0

    @property
    def amount_paid(self):
        """Calculate total amount paid for this invoice"""
        from django.db.models import Sum
        return self.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    @property
    def amount_outstanding(self):
        """Calculate outstanding amount for this invoice"""
        total = self.total_amount or Decimal('0')
        paid = self.amount_paid
        return max(Decimal('0'), total - paid)

    @property
    def is_overdue(self):
        """Check if invoice is overdue from related sale"""
        return self.sale.days_overdue > 0 if self.sale else False

    @property
    def can_fiscalize_status(self):
        """Check if invoice can be fiscalized (EFRIS compatible)"""
        return self.fiscalization_status == 'pending'

    @property
    def efris_is_fiscalized(self):
        """Check if invoice is fiscalized (EFRIS compatible)"""
        return self.fiscalization_status == 'fiscalized'

    def update_status(self):
        """Update invoice status based on sale payment status"""
        # This is now handled by the Sale model
        pass

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

        # Also update the sale with EFRIS data
        self.sale.efris_invoice_number = self.fiscal_document_number
        self.sale.verification_code = self.verification_code
        self.sale.is_fiscalized = True
        self.sale.fiscalization_time = self.fiscalization_time
        self.sale.save(update_fields=[
            'efris_invoice_number', 'verification_code', 'is_fiscalized', 'fiscalization_time'
        ])

        return True

    def mark_fiscalization_failed(self, reason=None):
        """Mark fiscalization as failed"""
        self.fiscalization_status = 'failed'
        self.is_fiscalized = False
        if reason:
            self.fiscalization_error = reason
        self.save(update_fields=['fiscalization_status', 'is_fiscalized', 'fiscalization_error'])

    def approve_ura_credit_note(self, approved_by=None):
        """Approve URA credit/debit note"""
        if self.efris_document_type not in ['2', '3']:
            raise ValidationError("URA approval only applies to credit/debit notes")

        if self.business_type not in ['B2B', 'B2G']:
            raise ValidationError("URA approval only required for B2B/B2G transactions")

        self.ura_approved = True
        self.ura_approval_date = timezone.now()
        self.save(update_fields=['ura_approved', 'ura_approval_date'])

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

            # Fiscalization metadata
            self.fiscalization_status = 'fiscalized'
            self.is_fiscalized = True
            self.fiscalization_time = timezone.now()
            updates.extend(['fiscalization_status', 'is_fiscalized', 'fiscalization_time'])

            # Save invoice updates
            if updates:
                self.save(update_fields=updates)

            # Update related sale
            self.update_sale_from_efris()

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update invoice {self.id} from EFRIS response: {e}", exc_info=True)
            raise

    def update_sale_from_efris(self):
        """Update related sale with EFRIS fiscalization data"""
        if not self.sale:
            return

        try:
            self.sale.efris_invoice_number = self.fiscal_document_number
            self.sale.verification_code = self.verification_code
            self.sale.qr_code = self.qr_code
            self.sale.is_fiscalized = True
            self.sale.fiscalization_time = self.fiscalization_time

            self.sale.save(update_fields=[
                'efris_invoice_number', 'verification_code', 'qr_code',
                'is_fiscalized', 'fiscalization_time'
            ])

            logger.info(f"Sale {self.sale.id} updated with fiscalization data")

        except Exception as e:
            logger.error(f"Failed to update sale {self.sale.id} from invoice fiscalization: {e}", exc_info=True)

    def get_efris_invoice_data(self):
        """Get complete invoice data formatted for EFRIS API"""
        if not self.sale:
            raise ValueError("Invoice must have an associated sale for EFRIS processing")

        # Use Sale's EFRIS mixin methods to build data (which now has VAT-aware logic)
        seller_details = self.sale.store.company.get_efris_seller_details() if hasattr(
            self.sale.store.company, 'get_efris_seller_details'
        ) else self._get_default_seller_details()

        buyer_details = {}
        if self.sale.customer and hasattr(self.sale.customer, 'get_efris_buyer_details'):
            buyer_details = self.sale.customer.get_efris_buyer_details()
        else:
            buyer_details = self._get_default_buyer_details()

        # Use the CORRECTED basic info from Sale model (VAT-aware)
        basic_info = self.sale.get_efris_basic_info()

        goods_details = self.sale.get_efris_goods_details() if hasattr(
            self.sale, 'get_efris_goods_details'
        ) else []

        summary = self.sale.get_efris_summary() if hasattr(
            self.sale, 'get_efris_summary'
        ) else self._get_default_summary()

        payment_details = self.sale.get_efris_payment_details() if hasattr(
            self.sale, 'get_efris_payment_details'
        ) else []

        # Build tax details
        tax_details = self._build_tax_details()

        return {
            "sellerDetails": seller_details,
            "basicInformation": basic_info,  # Now has correct invoiceKind
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
            "issuedDate": self.sale.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.sale else timezone.now().strftime(
                '%Y-%m-%d %H:%M:%S'),
            "operator": self.operator_name or 'System',
            "currency": self.sale.currency if self.sale else 'UGX',
            "invoiceType": "1",
            "invoiceKind": self.efris_document_type or "1",
        }

    def _get_default_summary(self):
        """Fallback summary if sale doesn't have EFRIS mixin"""
        net_amount = self.sale.subtotal - (self.sale.discount_amount or 0) if self.sale else Decimal('0')
        return {
            "netAmount": str(net_amount),
            "taxAmount": str(self.sale.tax_amount if self.sale else 0),
            "grossAmount": str(self.sale.total_amount if self.sale else 0),
            "itemCount": str(self.sale.item_count if self.sale else 1),
            "modeCode": "1",
            "remarks": self.sale.notes or "Invoice generated via system" if self.sale else "Invoice generated via system"
        }

    def _build_tax_details(self):
        """Build tax details for EFRIS"""
        net_amount = self.sale.subtotal - (self.sale.discount_amount or 0) if self.sale else Decimal('0')
        tax_amount = self.sale.tax_amount if self.sale else Decimal('0')
        total_amount = self.sale.total_amount if self.sale else Decimal('0')

        tax_details = []

        if tax_amount and tax_amount > 0:
            tax_details.append({
                "taxCategoryCode": "01",  # Standard VAT
                "netAmount": str(net_amount),
                "taxRate": "0.18",  # 18% VAT
                "taxAmount": str(tax_amount),
                "grossAmount": str(total_amount),
                "taxRateName": "Standard Rate (18%)"
            })
        else:
            tax_details.append({
                "taxCategoryCode": "02",  # Zero rate
                "netAmount": str(net_amount),
                "taxRate": "0.00",
                "taxAmount": "0",
                "grossAmount": str(total_amount),
                "taxRateName": "Zero Rate (0%)"
            })

        return tax_details


    @property
    def status(self):
        """Get status from related sale"""
        return self.sale.status if self.sale else 'DRAFT'

    @property
    def payment_status(self):
        """Get payment status from related sale"""
        return self.sale.payment_status if self.sale else 'PENDING'

    def create_payment_schedule(self, installments=1, first_due_date=None):
        """
        Create payment schedule for invoice

        Args:
            installments: Number of payment installments
            first_due_date: Date of first installment (defaults to invoice due_date)
        """
        if not first_due_date:
            first_due_date = self.due_date or (timezone.now().date() + timedelta(days=30))

        if installments < 1:
            raise ValidationError("Number of installments must be at least 1")

        # Clear existing schedules
        self.payment_schedules.all().delete()

        # Calculate installment amount
        installment_amount = (self.total_amount / installments).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        # Handle rounding difference in last installment
        total_allocated = Decimal('0')

        for i in range(1, installments + 1):
            # Last installment gets the remainder
            if i == installments:
                amount = self.total_amount - total_allocated
            else:
                amount = installment_amount
                total_allocated += amount

            # Calculate due date (30 days apart by default)
            due_date = first_due_date + timedelta(days=(i - 1) * 30)

            PaymentSchedule.objects.create(
                invoice=self,
                installment_number=i,
                due_date=due_date,
                expected_amount=amount
            )

        logger.info(f"Created {installments} payment schedules for invoice {self.id}")

    def allocate_payment_to_schedules(self, payment, user=None):
        """
        Allocate payment amount across unpaid schedules (oldest first)
        Returns: (allocations, remaining_amount)
        """
        remaining_amount = payment.amount
        allocations = []

        # Get unpaid schedules ordered by due date (oldest first)
        unpaid_schedules = self.payment_schedules.filter(
            status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
        ).order_by('due_date')

        for schedule in unpaid_schedules:
            if remaining_amount <= 0:
                break

            schedule_outstanding = schedule.amount_outstanding
            allocate_amount = min(remaining_amount, schedule_outstanding)

            if allocate_amount > 0:
                # Create allocation record
                allocation = PaymentAllocation.objects.create(
                    payment=payment,
                    payment_schedule=schedule,
                    allocated_amount=allocate_amount,
                    notes=f"Auto-allocated from payment #{payment.id}"
                )
                allocations.append(allocation)

                # Update schedule
                schedule.amount_paid += allocate_amount
                schedule.update_status()
                schedule.save()

                remaining_amount -= allocate_amount

        return allocations, remaining_amount

    def apply_payment(self, amount, payment_method, user, transaction_ref=None, notes=''):
        """
        Apply payment to invoice and update all related records
        Returns: (payment, allocations, remaining_credit)
        """
        with transaction.atomic():
            # Validate amount
            if amount <= 0:
                raise ValidationError("Payment amount must be positive")

            current_outstanding = self.amount_outstanding
            if amount > current_outstanding:
                raise ValidationError(
                    f"Payment amount {amount} exceeds outstanding amount {current_outstanding}"
                )

            # ✅ Create payment record
            payment = InvoicePayment.objects.create(
                invoice=self,
                amount=amount,
                payment_method=payment_method,
                transaction_reference=transaction_ref,
                processed_by=user,
                notes=notes,
                payment_date=timezone.now().date()
            )

            # Allocate to schedules if they exist
            allocations = []
            remaining_credit = Decimal('0')
            if hasattr(self, 'payment_schedules') and self.payment_schedules.exists():
                allocations, remaining_credit = self.allocate_payment_to_schedules(payment, user)

            # ✅ Mark payment as allocated
            payment.is_allocated = True
            payment.allocated_date = timezone.now()

            # ✅ Use update() to avoid triggering save() again
            InvoicePayment.objects.filter(pk=payment.pk).update(
                is_allocated=True,
                allocated_date=timezone.now()
            )

            # ✅ CRITICAL FIX: Force multiple status updates to ensure it sticks
            self.refresh_from_db()
            self.sale.refresh_from_db()

            # Update payment status
            new_status = self.update_payment_status(commit=True)

            # ✅ Refresh again to verify
            self.refresh_from_db()
            self.sale.refresh_from_db()

            # ✅ Create sales Payment record
            from sales.models import Payment as SalePayment
            try:
                sale_payment = SalePayment.objects.create(
                    sale=self.sale,
                    store=self.sale.store,
                    amount=amount,
                    payment_method=payment_method,
                    transaction_reference=transaction_ref,
                    is_confirmed=True,
                    confirmed_at=timezone.now(),
                    created_by=user,
                    payment_type='FULL' if amount >= self.total_amount else 'PARTIAL',
                    notes=f"Invoice payment - {notes or ''}"
                )

                # ✅ Trigger sale payment status update again
                self.sale.update_payment_status()
                self.sale.refresh_from_db()

            except Exception as e:
                logger.error(f"Error creating sales Payment record: {e}", exc_info=True)

            # Update customer credit balance if applicable
            if self.sale.customer and self.sale.customer.allow_credit:
                try:
                    self.sale.customer.update_credit_balance()
                except Exception as e:
                    logger.error(f"Error updating customer credit balance: {e}")

            return payment, allocations, remaining_credit

    def mark_as_fully_paid(self, user=None):
        """Mark invoice as fully paid"""
        if self.sale.payment_status != 'PAID':
            # Apply payment for remaining balance
            remaining = self.amount_outstanding
            if remaining > 0:
                self.apply_payment(
                    amount=remaining,
                    payment_method='CASH',  # Default
                    user=user,
                    notes='Marked as fully paid'
                )

            # Update status
            self.sale.payment_status = 'PAID'
            self.sale.status = 'COMPLETED'
            self.sale.save(update_fields=['payment_status', 'status', 'updated_at'])

            logger.info(f"Invoice {self.id} marked as fully paid by {user}")

    def allocate_payment(self, payment_amount, payment_method='CASH',
                         transaction_reference=None, processed_by=None, notes=''):
        """
        Allocate a payment to invoice and update payment schedules

        Returns: InvoicePayment object
        """
        with transaction.atomic():
            # Create payment record
            invoice_payment = InvoicePayment.objects.create(
                invoice=self,
                amount=payment_amount,
                payment_method=payment_method,
                transaction_reference=transaction_reference,
                processed_by=processed_by,
                notes=notes
            )

            # Allocate to payment schedules (FIFO - oldest first)
            remaining_amount = payment_amount
            schedules = self.payment_schedules.filter(
                status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
            ).order_by('due_date')

            for schedule in schedules:
                if remaining_amount <= 0:
                    break

                outstanding = schedule.amount_outstanding
                allocation = min(remaining_amount, outstanding)

                # Create allocation record
                PaymentAllocation.objects.create(
                    payment=invoice_payment,
                    payment_schedule=schedule,
                    allocated_amount=allocation,
                    notes=f"Auto-allocated to installment {schedule.installment_number}"
                )

                # Update schedule
                schedule.amount_paid += allocation
                schedule.update_status()

                remaining_amount -= allocation

            # Update invoice payment status
            self.update_payment_status()

            logger.info(
                f"Allocated payment of {payment_amount} to invoice {self.invoice_number}"
            )

            return invoice_payment

    def update_payment_status(self, commit=True):
        """
        Update invoice and sale payment status based on ALL payments
        """
        from django.db.models import Sum
        from decimal import Decimal

        # Calculate total paid from ALL confirmed payments
        total_paid = self.payments.filter(
            is_allocated=True
        ).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        # Ensure proper Decimal comparison
        total_amount = Decimal(str(self.sale.total_amount or 0))
        total_paid = Decimal(str(total_paid))

        # Calculate outstanding
        amount_outstanding = max(Decimal('0'), total_amount - total_paid)

        # DEBUG LOG
        logger.info(
            f"💰 Payment Status Calculation for Invoice {self.invoice_number}: "
            f"Total Amount: {total_amount}, "
            f"Total Paid: {total_paid}, "
            f"Outstanding: {amount_outstanding}"
        )

        # Determine payment status with explicit Decimal comparison
        if amount_outstanding <= Decimal('0.01'):  # Allow 1 cent tolerance
            new_payment_status = 'PAID'
            new_status = 'COMPLETED'
        elif total_paid > Decimal('0'):
            new_payment_status = 'PARTIALLY_PAID'
            new_status = 'PENDING_PAYMENT'
        else:
            new_payment_status = 'PENDING'
            new_status = 'PENDING_PAYMENT'

        # Check if overdue (only if not fully paid)
        if new_payment_status != 'PAID':
            if self.sale.due_date and self.sale.due_date < timezone.now().date():
                new_payment_status = 'OVERDUE'

        # Update sale fields
        old_payment_status = self.sale.payment_status
        old_status = self.sale.status

        self.sale.payment_status = new_payment_status
        self.sale.status = new_status

        if commit:
            # ✅ FIX: Use self.sale.__class__ to avoid import
            sale_model = self.sale.__class__
            sale_model.objects.filter(pk=self.sale.pk).update(
                payment_status=new_payment_status,
                status=new_status,
                updated_at=timezone.now()
            )

            # Refresh to get updated values
            self.sale.refresh_from_db()

            logger.info(
                f"✅ Invoice {self.invoice_number} status updated: "
                f"Payment Status: {old_payment_status} → {self.sale.payment_status}, "
                f"Status: {old_status} → {self.sale.status}"
            )

            # Update customer credit balance if applicable
            if self.sale.customer and self.sale.customer.allow_credit:
                try:
                    self.sale.customer.update_credit_balance()
                except Exception as e:
                    logger.error(f"Error updating customer credit balance: {e}")

        return new_payment_status

    def get_next_schedule_due(self):
        """Get next unpaid payment schedule"""
        return self.payment_schedules.filter(
            status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
        ).order_by('due_date').first()

    def get_overdue_schedules(self):
        """Get all overdue payment schedules"""
        return self.payment_schedules.filter(
            status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE'],
            due_date__lt=timezone.now().date()
        )

    @property
    def has_overdue_payments(self):
        """Check if invoice has any overdue payments"""
        return self.get_overdue_schedules().exists()

    @property
    def payment_completion_percentage(self):
        """Calculate percentage of invoice paid"""
        if self.total_amount == 0:
            return Decimal('0')
        return (self.amount_paid / self.total_amount * 100).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

    @property
    def next_payment_due(self):
        """Get next payment due date and amount"""
        next_schedule = self.get_next_schedule_due()
        if next_schedule:
            return {
                'due_date': next_schedule.due_date,
                'amount': next_schedule.amount_outstanding,
                'installment': next_schedule.installment_number
            }
        return None

    @property
    def get_total_paid(self):
        """Get total amount paid for this invoice"""
        return self.amount_paid

    @property
    def get_balance_due(self):
        """Get balance due for this invoice"""
        return self.amount_outstanding

    @transaction.atomic
    def process_payment(self, amount, payment_method, transaction_reference=None,
                        processed_by=None, notes=''):
        """
        Process a payment and allocate it to schedules
        """
        # Validate amount
        if amount <= 0:
            raise ValidationError("Payment amount must be positive")

        # Create payment record
        payment = InvoicePayment.objects.create(
            invoice=self,
            amount=amount,
            payment_method=payment_method,
            transaction_reference=transaction_reference,
            processed_by=processed_by,
            notes=notes,
            payment_date=timezone.now().date()
        )

        # Allocate to schedules
        allocations, remaining_credit = self.allocate_payment_to_schedules(payment)

        # Update invoice and sale status
        self.update_payment_status()

        # If invoice is fully paid, trigger completion
        if self.amount_outstanding <= 0:
            self.mark_as_fully_paid()

        return payment, allocations, remaining_credit


    def get_payment_summary(self):
        """Get detailed payment summary"""
        total_paid = self.payments.filter(is_allocated=True).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        return {
            'total_amount': self.total_amount,
            'amount_paid': total_paid,
            'amount_outstanding': self.total_amount - total_paid,
            'payment_count': self.payments.filter(is_allocated=True).count(),
            'payment_percentage': (total_paid / self.total_amount * 100) if self.total_amount > 0 else 0,
            'has_credit': self.payments.filter(is_allocated=False).exists(),
        }


    def can_fiscalize(self, user=None):
        """Enhanced fiscalization validation"""
        if self.fiscalization_status == 'fiscalized':
            return False, "Invoice is already fiscalized"

        if not self.sale or self.sale.status not in ['COMPLETED', 'PAID', 'PARTIALLY_PAID']:
            return False, "Only completed or paid invoices can be fiscalized"

        # Check company EFRIS configuration
        if not self.sale.store:
            return False, "Invoice must be associated with a store"

        store_config = self.sale.store.effective_efris_config
        if not store_config.get('enabled', False):
            return False, "EFRIS is not enabled for this store"

        # Check if sale can be fiscalized
        sale_can_fiscalize, sale_reason = self.sale.can_fiscalize(user)
        if not sale_can_fiscalize:
            return False, f"Related sale cannot be fiscalized: {sale_reason}"

        # Check for required EFRIS data
        if not self.sale.total_amount or self.sale.total_amount <= 0:
            return False, "Invoice must have a positive total amount"

        # Document type specific checks
        if self.efris_document_type in ['2', '3']:
            if self.business_type in ['B2B', 'B2G'] and not self.ura_approved:
                return False, "URA approval required for B2B/B2G credit/debit notes"

            if not self.original_fdn:
                return False, "Original fiscal document number required for credit/debit notes"

        return True, "Invoice can be fiscalized"



class PaymentSchedule(models.Model):
    """Track expected payment installments for invoices"""
    invoice = models.ForeignKey(
        'Invoice',
        on_delete=models.CASCADE,
        related_name='payment_schedules'
    )
    installment_number = models.PositiveIntegerField(
        verbose_name="Installment Number"
    )
    due_date = models.DateField(
        verbose_name="Due Date"
    )
    expected_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('PENDING', 'Pending'),
            ('PARTIALLY_PAID', 'Partially Paid'),
            ('PAID', 'Paid'),
            ('OVERDUE', 'Overdue'),
        ],
        default='PENDING'
    )
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['installment_number']
        unique_together = ['invoice', 'installment_number']
        verbose_name = "Payment Schedule"
        verbose_name_plural = "Payment Schedules"

    def __str__(self):
        return f"Installment {self.installment_number} - {self.invoice.invoice_number}"

    @property
    def amount_outstanding(self):
        return max(Decimal('0'), self.expected_amount - self.amount_paid)

    @property
    def is_overdue(self):
        return (
                self.status != 'PAID' and
                self.due_date < timezone.now().date()
        )

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (timezone.now().date() - self.due_date).days

    def update_status(self):
        """Auto-update status based on payment"""
        if self.amount_paid >= self.expected_amount:
            self.status = 'PAID'
        elif self.amount_paid > 0:
            self.status = 'PARTIALLY_PAID'
        elif self.is_overdue:
            self.status = 'OVERDUE'
        else:
            self.status = 'PENDING'
        self.save(update_fields=['status'])


class PaymentReminder(models.Model):
    """Track payment reminders sent to customers"""
    REMINDER_TYPE_CHOICES = [
        ('UPCOMING', 'Upcoming Payment'),
        ('DUE', 'Payment Due'),
        ('OVERDUE', 'Payment Overdue'),
        ('FINAL_NOTICE', 'Final Notice'),
    ]

    REMINDER_METHOD_CHOICES = [
        ('EMAIL', 'Email'),
        ('SMS', 'SMS'),
        ('WHATSAPP', 'WhatsApp'),
        ('LETTER', 'Physical Letter'),
    ]

    invoice = models.ForeignKey(
        'Invoice',
        on_delete=models.CASCADE,
        related_name='reminders'
    )
    payment_schedule = models.ForeignKey(
        'PaymentSchedule',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reminders',
        help_text="Specific installment being reminded about"
    )
    reminder_type = models.CharField(
        max_length=20,
        choices=REMINDER_TYPE_CHOICES
    )
    reminder_method = models.CharField(
        max_length=20,
        choices=REMINDER_METHOD_CHOICES,
        default='EMAIL'
    )
    sent_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Tracking
    is_successful = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, null=True)

    # Email/SMS specific
    recipient_email = models.EmailField(blank=True, null=True)
    recipient_phone = models.CharField(max_length=20, blank=True, null=True)
    subject = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField(blank=True, null=True)

    # Response tracking
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)

    # Next reminder scheduling
    next_reminder_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-sent_at']
        verbose_name = "Payment Reminder"
        verbose_name_plural = "Payment Reminders"
        indexes = [
            models.Index(fields=['invoice', 'sent_at']),
            models.Index(fields=['reminder_type']),
            models.Index(fields=['next_reminder_date']),
        ]

    def __str__(self):
        return f"{self.get_reminder_type_display()} - {self.invoice.invoice_number}"


class PaymentAllocation(models.Model):
    """
    Track how payments are allocated across invoice line items
    Useful for complex partial payments
    """
    payment = models.ForeignKey(
        'InvoicePayment',
        on_delete=models.CASCADE,
        related_name='allocations'
    )
    payment_schedule = models.ForeignKey(
        'PaymentSchedule',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='allocations'
    )
    allocated_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )
    allocation_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Payment Allocation"
        verbose_name_plural = "Payment Allocations"

    def __str__(self):
        return f"{self.allocated_amount} allocated to installment {self.payment_schedule.installment_number if self.payment_schedule else 'N/A'}"

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
    is_allocated = models.BooleanField(default=False)
    allocated_date = models.DateTimeField(null=True, blank=True)
    allocation_notes = models.TextField(blank=True, null=True)
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
        """Validate payment amount"""
        super().clean()

        if not self.invoice_id:
            return

        # Check if amount exceeds outstanding
        outstanding = self.invoice.amount_outstanding

        # If updating existing payment, add back current amount
        if self.pk:
            try:
                current_payment = InvoicePayment.objects.get(pk=self.pk)
                outstanding += current_payment.amount
            except InvoicePayment.DoesNotExist:
                pass

        if self.amount > outstanding:
            raise ValidationError({
                'amount': f'Payment amount ({self.amount}) cannot exceed outstanding invoice amount ({outstanding})'
            })

    def save(self, *args, **kwargs):
        """Save payment and update sale/invoice status"""
        # Run validation
        self.clean()

        is_new = not self.pk

        # Save the payment first
        super().save(*args, **kwargs)

        # ✅ FIX: Always update invoice/sale payment status after saving
        if is_new and self.invoice:
            try:
                # Force immediate update of invoice payment status
                self.invoice.update_payment_status(commit=True)

                # Double-check: Refresh and verify
                self.invoice.refresh_from_db()
                self.invoice.sale.refresh_from_db()

                logger.info(
                    f"✅ Payment {self.id} saved and status updated: "
                    f"Invoice={self.invoice.invoice_number}, "
                    f"Amount={self.amount}, "
                    f"Sale Status={self.invoice.sale.status}, "
                    f"Payment Status={self.invoice.sale.payment_status}"
                )
            except Exception as e:
                logger.error(
                    f"❌ Error updating payment status after payment {self.id}: {e}",
                    exc_info=True
                )

    def allocate_payment(self):
        """Allocate this payment to the invoice's payment schedules"""
        if self.is_allocated:
            return

        invoice = self.invoice

        # Allocate payment to schedules if they exist
        if hasattr(invoice, 'payment_schedules'):
            allocations, remaining_credit = invoice.allocate_payment_to_schedules(self)

        # Mark payment as allocated
        self.is_allocated = True
        self.allocated_date = timezone.now()

        # Save without triggering another save() cycle
        super(InvoicePayment, self).save(update_fields=['is_allocated', 'allocated_date'])

    def allocate_to_invoice(self):
        """Allocate payment to the invoice and update status"""
        if self.is_allocated:
            return

        invoice = self.invoice

        # Allocate to payment schedules if they exist
        allocations = []
        remaining = Decimal('0')
        if hasattr(invoice, 'payment_schedules') and invoice.payment_schedules.exists():
            allocations, remaining = invoice.allocate_payment_to_schedules(self, self.processed_by)

            # Log remaining amount if any
            if remaining > 0:
                logger.info(f"Payment {self.id} has {remaining} unallocated amount")

        # Mark as allocated
        self.is_allocated = True
        self.allocated_date = timezone.now()

        # Save without triggering save() again
        super(InvoicePayment, self).save(update_fields=['is_allocated', 'allocated_date'])

        # Force update of invoice payment status
        invoice.update_payment_status()

        # Create sales Payment record
        try:
            from sales.models import Payment as SalePayment
            SalePayment.objects.create(
                sale=invoice.sale,
                store=invoice.sale.store,
                amount=self.amount,
                payment_method=self.payment_method,
                transaction_reference=self.transaction_reference,
                is_confirmed=True,
                confirmed_at=timezone.now(),
                created_by=self.processed_by,
                payment_type='FULL' if self.amount >= invoice.total_amount else 'PARTIAL',
                notes=f"Invoice payment - {self.notes or ''}"
            )

            # Update sale payment status again to ensure consistency
            invoice.sale.update_payment_status()

        except Exception as e:
            logger.error(f"Failed to create sales Payment record: {e}")


    def delete(self, *args, **kwargs):
        invoice = self.invoice
        super().delete(*args, **kwargs)

        # Delete corresponding payment in sales app
        from sales.models import Payment
        Payment.objects.filter(
            sale=invoice.sale,
            amount=self.amount,
            payment_method=self.payment_method,
            transaction_reference=self.transaction_reference
        ).delete()

    def __str__(self):
        return f"Payment of {self.amount} for {self.invoice.sale.document_number}"


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
        return f"{self.action} - {self.invoice.sale.document_number}"