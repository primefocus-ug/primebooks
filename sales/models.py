from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import uuid
from django.conf import settings
from decimal import InvalidOperation
from django.db import transaction, IntegrityError
from django.db.models import F
from decimal import Decimal, ROUND_HALF_UP
from inventory.models import Stock,StockMovement
from django.utils import timezone

from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


class EFRISSaleMixin:
    """Sale-specific EFRIS methods - add to Sale model"""

    def can_fiscalize(self, user=None):
        """Check if sale can be fiscalized with detailed validation"""
        if self.is_fiscalized:
            return False, "Sale is already fiscalized"

        if not self.is_completed:
            return False, "Sale must be completed before fiscalization"

        if self.is_voided:
            return False, "Voided sales cannot be fiscalized"

        if self.is_refunded:
            return False, "Refunded sales cannot be fiscalized"

        if not self.total_amount or self.total_amount <= 0:
            return False, "Sale must have a positive total amount"

        # Check age - sales older than 30 days may have issues
        if self.created_at:
            days_old = (timezone.now().date() - self.created_at.date()).days
            if days_old > 30:
                return False, f"Sale is too old ({days_old} days). Maximum recommended age is 30 days"

        # Check if company has EFRIS enabled
        if not getattr(self.store.company, 'efris_enabled', False):
            return False, "EFRIS is not enabled for this company"

        return True, "Sale can be fiscalized"

    def get_efris_basic_info(self):
        """Get basic information for EFRIS invoice"""
        return {
            "invoiceNo": "",  # Will be assigned by EFRIS
            "issuedDate": self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            "operator": getattr(self, 'operator_name', 'System'),
            "currency": self.currency or 'UGX',
            "invoiceType": "1",  # Standard invoice
            "invoiceKind": "1",  # Normal invoice
            "dataSource": "103",  # WebService API
            "invoiceIndustryCode": "101"  # General Industry
        }

    def get_efris_summary(self):
        """Get summary information for EFRIS"""
        net_amount = self.subtotal - (self.discount_amount or 0)

        return {
            "netAmount": str(net_amount),
            "taxAmount": str(self.tax_amount or 0),
            "grossAmount": str(self.total_amount),
            "itemCount": str(self.item_count),
            "modeCode": "1",  # Online mode
            "remarks": self.notes or "Sale processed via system"
        }

    def get_efris_goods_details(self):
        """Get goods details for EFRIS from sale items"""
        goods_details = []

        for idx, item in enumerate(self.items.select_related('product').all(), 1):
            # Get EFRIS product data if available
            product_efris_data = {}
            if hasattr(item.product, 'get_efris_goods_data'):
                try:
                    product_efris_data = item.product.get_efris_goods_data()
                except:
                    pass

            goods_detail = {
                "item": product_efris_data.get('goodsName', item.product.name),
                "itemCode": product_efris_data.get('goodsCode', item.product.sku or f'ITEM{idx:04d}'),
                "qty": str(item.quantity),
                "unitOfMeasure": product_efris_data.get('measureUnit', 'U'),
                "unitPrice": str(item.unit_price),
                "total": str(item.total_price),
                "taxRate": self._get_efris_tax_rate_string(item.tax_rate),
                "tax": str(item.tax_amount or 0),
                "orderNumber": str(idx),
                "discountFlag": "1" if (item.discount_amount or 0) > 0 else "2",
                "deemedFlag": "2",  # Not deemed
                "exciseFlag": "2",  # No excise duty by default
                "goodsCategoryId": product_efris_data.get('commodityCategoryId', '1010101000'),
                "goodsCategoryName": "General Goods"
            }

            # Add discount information if applicable
            if item.discount_amount and item.discount_amount > 0:
                goods_detail["discountTotal"] = str(item.discount_amount)

            goods_details.append(goods_detail)

        return goods_details

    def get_efris_payment_details(self):
        """Get payment details for EFRIS"""
        payment_details = []

        if hasattr(self, 'payments') and self.payments.exists():
            for idx, payment in enumerate(self.payments.all(), 1):
                payment_mode = self._get_efris_payment_mode(payment.payment_method)
                payment_details.append({
                    "paymentMode": payment_mode,
                    "paymentAmount": str(payment.amount),
                    "orderNumber": chr(ord('a') + idx - 1)
                })
        else:
            # Default payment based on sale payment method
            payment_mode = self._get_efris_payment_mode(self.payment_method)
            payment_details.append({
                "paymentMode": payment_mode,
                "paymentAmount": str(self.total_amount),
                "orderNumber": "a"
            })

        return payment_details

    def _get_efris_tax_rate_string(self, tax_rate_code):
        """Convert tax rate code to EFRIS string value"""
        tax_rate_mapping = {
            'A': '0.18',  # Standard VAT 18%
            'B': '0.00',  # Zero rate
            'C': '-',  # Exempt
            'D': '0.18',  # Deemed rate
            'E': '0.18'  # Excise duty (fallback)
        }
        return tax_rate_mapping.get(str(tax_rate_code).upper(), '0.18')

    def _get_efris_payment_mode(self, payment_method):
        """Map payment method to EFRIS payment mode"""
        payment_modes = {
            'CASH': '102',
            'CARD': '106',
            'MOBILE_MONEY': '105',
            'BANK_TRANSFER': '107',
            'VOUCHER': '101',
            'CREDIT': '101'
        }
        return payment_modes.get(payment_method.upper(), '102')

class Sale(models.Model,EFRISSaleMixin):
    PAYMENT_METHODS = [
        ('CASH', 'Cash'),
        ('CARD', 'Credit Card'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('VOUCHER', 'Voucher'),
        ('CREDIT', 'Customer Credit'),
    ]

    DOCUMENT_TYPES = [
        ('ORIGINAL', 'Original'),
        ('COPY', 'Copy'),
        ('CREDIT_NOTE', 'Credit Note'),
        ('DEBIT_NOTE', 'Debit Note'),
    ]

    TRANSACTION_TYPES = [
        ('SALE', 'Sale'),
        ('REFUND', 'Refund'),
        ('VOID', 'Void'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('voided', 'Voided'),
        ('refunded', 'Refunded'),
    ]

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    transaction_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    invoice_number = models.CharField(max_length=50, blank=True, null=True, unique=True, db_index=True)

    store = models.ForeignKey('stores.Store', on_delete=models.PROTECT, related_name='sales')
    created_by = models.ForeignKey('accounts.CustomUser', on_delete=models.PROTECT, related_name='created_sales')
    customer = models.ForeignKey('customers.Customer', on_delete=models.SET_NULL, null=True, blank=True)

    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, default='SALE')
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES, default='ORIGINAL')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS,default='CASH')
    currency = models.CharField(max_length=3, default='UGX')

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)], default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)], default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)], default=0)

    # EFRIS
    efris_invoice_number = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    verification_code = models.CharField(max_length=100, blank=True, null=True)
    qr_code = models.TextField(blank=True, null=True)
    is_fiscalized = models.BooleanField(default=False, db_index=True)
    fiscalization_time = models.DateTimeField(blank=True, null=True)
    fiscal_number = models.CharField(max_length=64, blank=True, null=True)
    fiscalization_status = models.CharField(max_length=32, blank=True, null=True, default='pending')

    is_completed = models.BooleanField(default=True)
    is_refunded = models.BooleanField(default=False)
    is_voided = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    duplicated_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="duplicates",
        help_text="If this sale was duplicated, reference the original sale"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    related_sale = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transaction_id']),
            models.Index(fields=['store', 'created_at']),
            models.Index(fields=['efris_invoice_number']),
            models.Index(fields=['is_fiscalized']),
            models.Index(fields=['customer']),
            models.Index(fields=['store', 'is_completed', 'created_at']),
        ]
        verbose_name = "Sale"
        verbose_name_plural = "Sales"

    def __str__(self):
        return f"Sale #{self.invoice_number or self.transaction_id}"

    def clean(self):
        """Model-level validation"""
        super().clean()

        subtotal = Decimal(self.subtotal or 0)
        tax = Decimal(self.tax_amount or 0)
        discount = Decimal(self.discount_amount or 0)
        total = Decimal(self.total_amount or 0)

        # ✅ For tax-inclusive prices:
        # total should equal subtotal - discount (not subtotal + tax)
        calculated_total = subtotal - discount

        if abs(total - calculated_total) > Decimal('0.01'):
            raise ValidationError("Total amount doesn't match calculated total")

        # Validate discount doesn't exceed subtotal
        if discount > subtotal:
            raise ValidationError("Discount amount cannot exceed subtotal")

    def save(self, *args, **kwargs):
        # Auto-generate invoice number if not provided
        if not self.invoice_number and self.transaction_type == 'SALE':
            self.invoice_number = f"INV-{timezone.now().strftime('%Y%m%d')}-{str(self.transaction_id)[:8]}"

        subtotal = Decimal(self.subtotal or 0)
        tax = Decimal(self.tax_amount or 0)
        discount = Decimal(self.discount_amount or 0)
        total = Decimal(self.total_amount or 0)

        # Ensure total amount with proper rounding
        if not self.total_amount or self.total_amount == 0:
            calculated_total = subtotal + tax - discount
            self.total_amount = calculated_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Run model validation
        self.full_clean()

        # Check if this is a new sale and if auto-invoice creation is enabled
        is_new = not self.pk

        super().save(*args, **kwargs)

        # Send WebSocket update only after successful save
        if self.is_completed:
            try:
                self.send_sale_update()
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"WebSocket update failed for sale {self.id}: {e}")

        # Check if we should auto-create invoice for EFRIS
        if is_new and self.is_completed and self.transaction_type == 'SALE':
            try:
                # Check company policy for auto-invoice creation
                if (hasattr(self.store, 'company') and
                        getattr(self.store.company, 'auto_create_invoices', False)):

                    # Defer invoice creation to avoid circular import issues
                    from django.db import transaction
                    if not transaction.get_autocommit():
                        # We're inside a transaction, schedule for later
                        transaction.on_commit(lambda: self._create_invoice_if_needed())
                    else:
                        self._create_invoice_if_needed()

            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Auto-invoice creation check failed for sale {self.id}: {e}")

    def update_totals(self):
        """Update totals using SaleItems with proper aggregation"""
        from django.db.models import Sum

        aggregates = self.items.aggregate(
            subtotal_sum=Sum('total_price'),
            discount_sum=Sum('discount_amount'),
            tax_sum=Sum('tax_amount')
        )

        subtotal = Decimal(aggregates['subtotal_sum'] or 0)
        discount = Decimal(aggregates['discount_sum'] or 0)
        tax = Decimal(aggregates['tax_sum'] or 0)

        self.subtotal = subtotal
        self.discount_amount = discount
        self.tax_amount = tax


        self.total_amount = (subtotal - discount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        # =============================================

        # Ensure total_amount is positive
        if self.total_amount < 0:
            self.total_amount = Decimal('0')

        self.save(update_fields=['subtotal', 'tax_amount', 'discount_amount', 'total_amount'])

    def send_sale_update(self):
        """Send WebSocket message for real-time updates per store"""
        if not hasattr(self, '_websocket_sent'):  # Prevent duplicate sends
            try:
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f'sales_{self.store.id}',
                        {
                            'type': 'sale_update',
                            'message': {
                                'sale_id': str(self.id),
                                'invoice_number': self.invoice_number,
                                'status': 'completed' if self.is_completed else 'pending',
                                'total_amount': str(self.total_amount),
                                'store_id': self.store.id,
                                'created_at': self.created_at.isoformat(),
                            }
                        }
                    )
                    self._websocket_sent = True
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"WebSocket Error for Sale {self.id}: {e}")

    @property
    def item_count(self):
        return self.items.count()

    @property
    def issue_date(self):
        """Provide issue_date for EFRIS compatibility"""
        return self.created_at

    @property
    def fiscal_document_number(self):
        """Provide fiscal_document_number for EFRIS compatibility"""
        return self.efris_invoice_number

    @property
    def items(self):
        """Get sale items - EFRIS expects this property"""
        return getattr(self, 'sale_items', self.items)

    @property
    def company(self):
        """Get company from store for EFRIS"""
        return self.store.company

    def update_from_efris_response(self, response_data):
        """Update sale with EFRIS fiscalization response data"""
        try:
            if not response_data:
                logger.warning(f"No EFRIS response data provided for sale {self.id}")
                return

            updates = {}

            # --- Extract main sections safely ---
            basic_info = response_data.get('basicInformation', {})
            summary = response_data.get('summary', {})
            data_section = response_data.get('data', {})

            # --- Fiscal document number ---
            fiscal_doc_number = (
                    basic_info.get('invoiceNo')
                    or response_data.get('invoiceNo')
                    or data_section.get('invoiceNo')
            )
            if fiscal_doc_number:
                updates['efris_invoice_number'] = fiscal_doc_number

            # --- Verification (Anti-fake) code ---
            verification_code = (
                    basic_info.get('antifakeCode')
                    or response_data.get('antifakeCode')
                    or data_section.get('antifakeCode')
            )
            if verification_code:
                updates['verification_code'] = verification_code

            # --- QR Code (handle variants) ---
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

            # --- Mark as fiscalized ---
            updates['is_fiscalized'] = True
            updates['fiscalization_time'] = timezone.now()

            # --- Apply updates ---
            if updates:
                for field, value in updates.items():
                    setattr(self, field, value)

                self.save(update_fields=list(updates.keys()))

                logger.info(f"✅ Sale {self.id} updated with fields: {list(updates.keys())}")
            else:
                logger.warning(f"No matching EFRIS fields found for sale {self.id}")

        except Exception as e:
            logger.error(f"❌ Failed to update sale {self.id} with EFRIS response: {e}", exc_info=True)

    def get_invoice_for_efris_processing(self):
        """Get the object to be used for EFRIS processing"""
        # If we have a separate invoice, use that
        if hasattr(self, 'invoice') and self.invoice:
            return self.invoice

        # Otherwise use the sale itself as the invoice
        return self
    @fiscal_document_number.setter
    def fiscal_document_number(self, value):
        """Set fiscal_document_number for EFRIS compatibility"""
        self.efris_invoice_number = value

    def can_fiscalize(self, user=None):
        """Check if this sale can be fiscalized"""
        if self.is_fiscalized:
            return False, "Sale is already fiscalized"

        if not self.is_completed:
            return False, "Sale is not completed"

        if self.is_voided:
            return False, "Sale is voided"

        if self.is_refunded:
            return False, "Sale is refunded"

        if self.total_amount <= 0:
            return False, "Sale has zero or negative total amount"

        if not hasattr(self.store, 'company') or not self.store.company.efris_enabled:
            return False, "EFRIS is not enabled for this store's company"

        return True, "Sale can be fiscalized"

    def mark_fiscalization_failed(self, error_message):
        """Mark sale fiscalization as failed"""
        self.fiscalization_error = error_message
        # You might want to add a fiscalization_status field to track this
        self.save(update_fields=['fiscalization_error'])

    def _create_invoice_if_needed(self):
        """Enhanced invoice creation with proper amount mapping"""
        try:
            # Check if invoice already exists
            if hasattr(self, 'invoice') and self.invoice:
                return self.invoice

            # Validate sale has positive amounts
            if self.total_amount <= 0:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Skipping invoice creation for sale {self.id} - zero or negative amount: {self.total_amount}")
                return None

            # Import here to avoid circular imports
            try:
                from invoices.models import Invoice
            except ImportError:
                # If no Invoice model, create a simple invoice-like object
                import logging
                logger = logging.getLogger(__name__)
                logger.warning("Invoice model not found, using Sale as invoice for EFRIS")
                return self

            # Create invoice with proper field mapping
            invoice_data = {
                'sale': self,
                'store': self.store,
                'customer': self.sale.customer,
                'created_by': self.created_by,
                'invoice_number': self.invoice_number,
                'issue_date': self.created_at,
                'due_date': self.created_at.date() + timedelta(days=30),  # Default 30 days
                'subtotal': self.subtotal,
                'tax_amount': self.tax_amount,
                'discount_amount': self.discount_amount,
                'total_amount': self.total_amount,
                'currency_code': self.currency,
                'payment_method': self.payment_method,
                'status': 'pending',
                'document_type': 'INVOICE',
            }

            invoice = Invoice.objects.create(**invoice_data)

            # Copy sale items to invoice items if needed
            self._copy_items_to_invoice(invoice)

            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                f"Created invoice {invoice.invoice_number} for sale {self.id} with amount {invoice.total_amount}")

            return invoice

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create invoice for sale {self.id}: {e}")
            return None

    def _copy_items_to_invoice(self, invoice):
        """Copy sale items to invoice items"""
        try:
            # Import invoice items model
            try:
                from invoices.models import InvoiceItem
            except ImportError:
                return  # Skip if no InvoiceItem model

            for sale_item in self.items.all():
                InvoiceItem.objects.create(
                    invoice=invoice,
                    product=sale_item.product,
                    quantity=sale_item.quantity,
                    unit_price=sale_item.unit_price,
                    total_price=sale_item.total_price,
                    tax_amount=getattr(sale_item, 'tax_amount', 0),
                    discount_amount=getattr(sale_item, 'discount_amount', 0),
                )

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to copy items to invoice for sale {self.id}: {e}")

    @property
    def total_quantity(self):
        from django.db.models import Sum
        result = self.items.aggregate(total=Sum('quantity'))
        return result['total'] or 0

    @transaction.atomic
    def void_sale(self, reason):
        """Void a sale and restore stock atomically"""
        if self.is_voided:
            raise ValidationError("Sale is already voided")

        self.is_voided = True
        self.void_reason = reason
        self.is_completed = False
        self.save()

        # Restore stock for all items
        for item in self.items.select_for_update():
            item.restore_stock()

    @transaction.atomic
    def process_refund(self):
        """Process a refund and restore stock atomically"""
        if self.is_refunded:
            raise ValidationError("Sale is already refunded")

        self.is_refunded = True
        self.save()

        # Restore stock for all items
        for item in self.items.select_for_update():
            item.restore_stock()

    def create_stock_movements_for_efris(self):
        """Create comprehensive stock movements for EFRIS audit trail"""
        try:
            for item in self.items.select_related('product'):
                # Create detailed stock movement with EFRIS reference
                movement_reference = self.efris_invoice_number or self.invoice_number or f"SALE-{self.id}"

                StockMovement.objects.create(
                    product=item.product,
                    store=self.store,
                    movement_type='SALE',
                    quantity=item.quantity,
                    reference=movement_reference,
                    unit_price=item.unit_price,
                    total_value=item.total_price,
                    created_by=self.created_by,
                    notes=f'EFRIS Sale: {movement_reference}' if self.is_fiscalized else f'Sale: {movement_reference}',
                    # Add EFRIS tracking fields if available
                    efris_reference=self.efris_invoice_number if self.is_fiscalized else None,
                    fiscal_document_number=self.efris_invoice_number if self.is_fiscalized else None
                )

            return True
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error creating EFRIS stock movements for sale {self.id}: {e}")
            return False

    def _create_invoice_if_needed(self):
        """Enhanced invoice creation with proper amount mapping"""
        try:
            # Check if invoice already exists
            if hasattr(self, 'invoice') and self.invoice:
                return self.invoice

            # Validate sale has positive amounts
            if self.total_amount <= 0:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Skipping invoice creation for sale {self.id} - zero or negative amount: {self.total_amount}")
                return None

            # Import here to avoid circular imports
            try:
                from invoices.models import Invoice
            except ImportError:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning("Invoice model not found, using Sale as invoice for EFRIS")
                return self

            # ========== FIXED: Removed 'customer' field ==========
            # Create invoice with proper field mapping
            invoice_data = {
                'sale': self,
                'store': self.store,
                # 'customer': self.customer,  # REMOVED - Invoice doesn't have this field
                'created_by': self.created_by,
                'invoice_number': self.invoice_number,
                'issue_date': self.created_at,
                'due_date': self.created_at.date() + timedelta(days=30),  # Default 30 days
                'subtotal': self.subtotal,
                'tax_amount': self.tax_amount,
                'discount_amount': self.discount_amount,
                'total_amount': self.total_amount,
                'currency_code': self.currency,
                'status': 'SENT',  # Changed from 'pending' to 'SENT'
                'document_type': 'INVOICE',
            }
            # =====================================================

            invoice = Invoice.objects.create(**invoice_data)

            # Copy sale items to invoice items if needed
            self._copy_items_to_invoice(invoice)

            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                f"Created invoice {invoice.invoice_number} for sale {self.id} with amount {invoice.total_amount}")

            return invoice

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create invoice for sale {self.id}: {e}")
            return None


class SaleItem(models.Model):
    TAX_RATE_CHOICES = [
        ('A', 'Standard rate (18%)'),
        ('B', 'Zero rate (0%)'),
        ('C', 'Exempt (Not taxable)'),
        ('D', 'Deemed rate (18%)'),
        ('E', 'Excise Duty rate (per product)'),
    ]

    sale = models.ForeignKey(Sale, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT, related_name='sale_items')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    total_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    tax_rate = models.CharField(max_length=1, choices=TAX_RATE_CHOICES, default='A')
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)], default=0)
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Sale Item"
        verbose_name_plural = "Sale Items"
        ordering = ['id']
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity__gt=0),
                name='positive_quantity'
            ),
            models.CheckConstraint(
                check=models.Q(unit_price__gte=0),
                name='non_negative_unit_price'
            ),
        ]

    def __str__(self):
        return f"{self.product.name} x {self.quantity} - {self.sale.invoice_number}"

    def clean(self):
        """Model-level validation"""
        super().clean()

        # Validate discount percentage
        if self.discount < 0 or self.discount > 100:
            raise ValidationError("Discount must be between 0 and 100 percent")

    def save(self, *args, **kwargs):
        # Calculate totals with proper rounding
        self.total_price = (self.unit_price * Decimal(self.quantity)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        self.discount_amount = (
            (self.discount / Decimal('100')) * self.total_price if self.discount else Decimal('0')
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        final_price = self.total_price - self.discount_amount

        # ========== FIXED TAX CALCULATION - Extract tax from selling price ==========
        # The selling price (final_price) INCLUDES tax, so we extract it
        if self.tax_rate in ['A', 'D']:
            # For 18% VAT: tax = price / 1.18 * 0.18
            self.tax_amount = (final_price / Decimal('1.18') * Decimal('0.18')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        elif self.tax_rate == 'E' and getattr(self.product, 'excise_duty_rate', None):
            excise_rate = self.product.excise_duty_rate / Decimal('100')
            # Extract excise tax from selling price
            self.tax_amount = (final_price / (Decimal('1') + excise_rate) * excise_rate).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        else:
            # Tax rates B (Zero) and C (Exempt) have no tax
            self.tax_amount = Decimal('0.00')
        # ============================================================================

        # Run model validation
        self.full_clean()

        # Only deduct stock for new items in completed sales
        is_new = not self.pk
        if is_new and self.sale.is_completed and self.sale.transaction_type == 'SALE':
            self.deduct_stock()

        super().save(*args, **kwargs)

        # Update sale totals after saving item
        if not getattr(self, '_skip_sale_update', False):
            self.sale.update_totals()

    @transaction.atomic
    def deduct_stock(self):
        """Enhanced stock deduction with better error handling and EFRIS tracking"""
        try:
            import logging
            logger = logging.getLogger(__name__)

            # BEFORE deduction
            store_stock = Stock.objects.select_for_update().filter(
                product=self.product,
                store=self.sale.store
            ).first()

            if not store_stock:
                raise ValidationError(
                    f"No stock available for product {self.product.name} in store {self.sale.store.name}"
                )

            old_quantity = store_stock.quantity
            logger.info(f"🔴 BEFORE DEDUCTION: {self.product.name} stock = {old_quantity}")

            if store_stock.quantity < self.quantity:
                raise ValidationError(
                    f"Insufficient stock in store {self.sale.store.name} for product {self.product.name}. "
                    f"Available: {store_stock.quantity}, Required: {self.quantity}"
                )

            # Use F() expressions to prevent race conditions
            updated_rows = Stock.objects.filter(id=store_stock.id).update(
                quantity=F('quantity') - self.quantity,
                last_updated=timezone.now()
            )

            # Refresh to see the new value
            store_stock.refresh_from_db()
            logger.info(f"🟢 AFTER F() DEDUCTION: {self.product.name} stock = {store_stock.quantity}")

            if updated_rows == 0:
                raise ValidationError("Stock update failed - record may have been modified by another transaction")

            # Create stock movement record
            movement_reference = (
                    self.sale.efris_invoice_number or
                    self.sale.invoice_number or
                    f"SALE-{self.sale.id}"
            )

            logger.info(f"📝 Creating StockMovement with quantity={self.quantity}, type=SALE")

            movement = StockMovement.objects.create(
                product=self.product,
                store=self.sale.store,
                movement_type='SALE',
                quantity=self.quantity,  # Positive quantity
                reference=movement_reference,
                unit_price=self.unit_price,
                total_value=self.total_price,
                created_by=self.sale.created_by,
                notes=f'Sale item: {self.product.name} - Qty: {self.quantity}',
            )

            # Check stock AFTER movement creation
            store_stock.refresh_from_db()
            logger.info(f"🔵 AFTER StockMovement.create(): {self.product.name} stock = {store_stock.quantity}")
            logger.info(f"Movement ID: {movement.id}, Type: {movement.movement_type}, Qty: {movement.quantity}")

        except Exception as e:
            logger.error(f"❌ Stock deduction error: {e}")
            raise

    @transaction.atomic
    def restore_stock(self):
        """Enhanced stock restoration with EFRIS audit trail"""
        try:
            # Restore store stock
            store_stock = Stock.objects.select_for_update().filter(
                product=self.product,
                store=self.sale.store
            ).first()

            if store_stock:
                Stock.objects.filter(id=store_stock.id).update(
                    quantity=F('quantity') + self.quantity,
                    last_updated=timezone.now()
                )

            # Restore general stock
            general_stock = Stock.objects.select_for_update().filter(
                product=self.product,
                store__isnull=True
            ).first()

            if general_stock:
                Stock.objects.filter(id=general_stock.id).update(
                    quantity=F('quantity') + self.quantity,
                    last_updated=timezone.now()
                )

            # Create restoration movement record
            movement_type = 'VOID' if self.sale.is_voided else 'REFUND'
            movement_reference = (
                    self.sale.efris_invoice_number or
                    self.sale.invoice_number or
                    f"RESTORE-{self.sale.id}"
            )

            StockMovement.objects.create(
                product=self.product,
                store=self.sale.store,
                movement_type=movement_type,
                quantity=self.quantity,  # ✅ Keep positive
                reference=movement_reference,
                unit_price=self.unit_price,
                total_value=self.total_price,
                created_by=self.sale.created_by,
                notes=f'Stock restoration: {movement_type.lower()} - {self.product.name}',
                efris_reference=self.sale.efris_invoice_number if self.sale.is_fiscalized else None
            )

            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                f"Stock restored successfully: {self.product.name} "
                f"(Qty: {self.quantity}) to store {self.sale.store.name}"
            )

        except IntegrityError as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Stock restoration failed: {e}")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Unexpected error during stock restoration: {e}")

    @property
    def line_total(self):
        """Compute total line amount (since tax is already in total_price, just subtract discount)"""
        total = self.total_price or Decimal("0.00")
        discount = self.discount_amount or Decimal("0.00")
        return total - discount

    @property
    def net_amount(self):
        """Return total price minus discount and tax (net before tax amount)"""
        total = self.total_price or Decimal("0.00")
        discount = self.discount_amount or Decimal("0.00")
        tax = self.tax_amount or Decimal("0.00")
        return total - discount - tax


class Receipt(models.Model):
    sale = models.OneToOneField(Sale, on_delete=models.CASCADE, related_name='receipt')
    store = models.ForeignKey('stores.Store', on_delete=models.PROTECT, null=True, blank=True)
    receipt_number = models.CharField(max_length=50, unique=True)
    printed_at = models.DateTimeField(auto_now_add=True)
    printed_by = models.ForeignKey('accounts.CustomUser', on_delete=models.PROTECT)
    receipt_data = models.JSONField()
    is_duplicate = models.BooleanField(default=False)
    print_count = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "Receipt"
        verbose_name_plural = "Receipts"
        ordering = ['-printed_at']

    def __str__(self):
        return f"Receipt #{self.receipt_number}"


class Payment(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='payments')
    store = models.ForeignKey('stores.Store', on_delete=models.PROTECT, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)])
    payment_method = models.CharField(max_length=20, choices=Sale.PAYMENT_METHODS)
    transaction_reference = models.CharField(max_length=100, blank=True, null=True)
    is_confirmed = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(blank=True, null=True)
    is_voided = models.BooleanField(default=False)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='voided_payments'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_created"
    )
    void_reason = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment of {self.amount} for Sale #{self.sale.invoice_number or self.sale.transaction_id}"


class Cart(models.Model):
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('CONFIRMED', 'Confirmed'),
        ('ABANDONED', 'Abandoned'),
    ]

    session_key = models.CharField(max_length=40, blank=True, null=True)
    user = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, null=True, blank=True)
    customer = models.ForeignKey('customers.Customer', on_delete=models.SET_NULL, null=True, blank=True)
    store = models.ForeignKey('stores.Store', on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Shopping Cart"
        verbose_name_plural = "Shopping Carts"
        ordering = ['-created_at']

    def __str__(self):
        return f"Cart #{self.id} - {self.get_status_display()}"

    def update_totals(self):
        """Update cart totals with proper aggregation"""
        from django.db.models import Sum

        aggregates = self.items.aggregate(
            subtotal_sum=Sum('total_price'),
            tax_sum=Sum('tax_amount'),
            discount_sum=Sum('discount_amount')
        )

        self.subtotal = aggregates['subtotal_sum'] or Decimal('0')
        self.tax_amount = aggregates['tax_sum'] or Decimal('0')
        self.discount_amount = aggregates['discount_sum'] or Decimal('0')

        # ========== FIXED TOTAL CALCULATION ==========
        # Since tax is already in subtotal, we just subtract discount
        self.total_amount = (self.subtotal - self.discount_amount).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        # =============================================

        self.save(update_fields=['subtotal', 'tax_amount', 'discount_amount', 'total_amount'])

    @transaction.atomic
    def confirm(self, payment_method, created_by):
        """Enhanced cart confirmation with EFRIS preparation"""
        if self.status != 'OPEN':
            raise ValidationError("Cart is not open for confirmation")

        # Validate stock availability with locking
        for item in self.items.select_related('product').select_for_update():
            store_stock = Stock.objects.select_for_update().filter(
                product=item.product,
                store=self.store
            ).first()

            if not store_stock or store_stock.quantity < item.quantity:
                raise ValidationError(
                    f"Insufficient stock for {item.product.name} in store {self.store.name}. "
                    f"Available: {store_stock.quantity if store_stock else 0}, Required: {item.quantity}"
                )

        # Create sale with EFRIS-aware data
        sale = Sale.objects.create(
            store=self.store,
            created_by=created_by,
            customer=self.customer,
            payment_method=payment_method,
            subtotal=self.subtotal,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            total_amount=self.total_amount,
            is_completed=True,
            notes=self.notes or '',
            # Add EFRIS-ready fields
            currency='UGX',  # Default currency
            transaction_type='SALE',
            document_type='ORIGINAL'
        )

        # Move cart items to SaleItems with proper EFRIS data
        for item in self.items.all():
            sale_item = SaleItem.objects.create(
                sale=sale,
                product=item.product,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_price=item.total_price,
                tax_rate=item.tax_rate,
                tax_amount=item.tax_amount,
                discount=item.discount,
                discount_amount=item.discount_amount,
                description=item.description or item.product.name,
                # Skip automatic stock deduction since we'll handle it manually
                _skip_sale_update=True
            )

            # Manually deduct stock to maintain atomicity
            sale_item.deduct_stock()

        # Update sale totals after all items are added
        sale.update_totals()

        self.status = 'CONFIRMED'
        self.save(update_fields=['status'])

        return sale

    def send_cart_update(self):
        """WebSocket updates for cart with error handling"""
        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f'cart_{self.id}',
                    {
                        'type': 'cart_update',
                        'message': {
                            'cart_id': str(self.id),
                            'subtotal': str(self.subtotal),
                            'total_amount': str(self.total_amount),
                            'item_count': self.items.count(),
                            'status': self.status
                        }
                    }
                )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"WebSocket Error for Cart {self.id}: {e}")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            self.send_cart_update()
        except Exception:
            pass  # Don't let WebSocket errors break cart operations


class CartItem(models.Model):
    TAX_RATE_CHOICES = SaleItem.TAX_RATE_CHOICES

    cart = models.ForeignKey(Cart, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.CharField(max_length=1, choices=TAX_RATE_CHOICES, default='A')
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    description = models.TextField(blank=True, null=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cart Item"
        verbose_name_plural = "Cart Items"
        ordering = ['added_at']
        constraints = [
            models.UniqueConstraint(
                fields=['cart', 'product'],
                name='unique_cart_product'
            ),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product.name} in Cart #{self.cart.id}"

    def save(self, *args, **kwargs):
        """Calculate totals, discounts, and tax with proper rounding"""
        self.total_price = (self.unit_price * Decimal(self.quantity)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        self.discount_amount = (
            (self.discount / Decimal('100')) * self.total_price if self.discount else Decimal('0')
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        final_price = self.total_price - self.discount_amount

        # ========== FIXED TAX CALCULATION - Extract tax from selling price ==========
        if self.tax_rate in ['A', 'D']:
            # For 18% VAT: extract tax from price that includes tax
            self.tax_amount = (final_price / Decimal('1.18') * Decimal('0.18')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        elif self.tax_rate == 'E':
            excise_rate = getattr(self.product, 'excise_duty_rate', 0) or 0
            try:
                excise_rate_decimal = Decimal(str(excise_rate)) / Decimal('100')
                # Extract excise tax from price that includes tax
                self.tax_amount = (final_price / (Decimal('1') + excise_rate_decimal) * excise_rate_decimal).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
            except (TypeError, InvalidOperation):
                self.tax_amount = Decimal('0')
        else:
            # Tax rates B (Zero) and C (Exempt) have no tax
            self.tax_amount = Decimal('0')
        # ============================================================================

        super().save(*args, **kwargs)

        # Update cart totals after saving
        if not getattr(self, '_skip_cart_update', False):
            self.cart.update_totals()

    def delete(self, *args, **kwargs):
        """Update cart totals when item is deleted"""
        cart = self.cart
        super().delete(*args, **kwargs)
        cart.update_totals()

    def available_stock(self):
        """Check current store stock for the product"""
        stock = Stock.objects.filter(
            product=self.product,
            store=self.cart.store
        ).first()
        return stock.quantity if stock else 0