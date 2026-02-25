from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import uuid
from django.conf import settings
from decimal import InvalidOperation
from django.db import transaction, IntegrityError
from django.db.models import F, Sum
from decimal import Decimal, ROUND_HALF_UP
from inventory.models import Stock, StockMovement
from datetime import timedelta
import logging
from primebooks.mixins import OfflineIDMixin

logger = logging.getLogger(__name__)


class EFRISSaleMixin:
    """Sale-specific EFRIS methods - ALL sales can be fiscalized"""

    def can_fiscalize(self, user=None):
        """
        Check if sale can be fiscalized
        ENHANCED: Better validation and error messages
        """
        # Already fiscalized check
        if self.is_fiscalized:
            return False, "Sale is already fiscalized"

        # Status check
        if self.status not in ['COMPLETED', 'PAID']:
            return False, f"Only completed or paid sales can be fiscalized. Current status: {self.status}"

        # Void/Refund checks
        if self.is_voided:
            return False, "Voided sales cannot be fiscalized"

        if self.is_refunded:
            return False, "Refunded sales cannot be fiscalized"

        # Amount validation
        if not self.total_amount or self.total_amount <= 0:
            return False, "Sale must have a positive total amount"

        # Items check
        if not self.items.exists():
            return False, "Sale must have at least one item"

        # Store configuration check
        try:
            store_config = self.store.effective_efris_config

            if not store_config.get('enabled', False):
                return False, "EFRIS is not enabled for this store"

            if not store_config.get('is_active', False):
                return False, "EFRIS configuration is not active for this store"

        except Exception as e:
            logger.error(f"Error checking EFRIS config: {e}")
            return False, f"Error checking EFRIS configuration: {str(e)}"

        # Age check - sales older than 30 days may have issues
        if self.created_at:
            days_old = (timezone.now().date() - self.created_at.date()).days
            if days_old > 30:
                return False, f"Sale is too old ({days_old} days). Maximum recommended age is 30 days"

        # User permission check (if provided)
        if user:
            if not hasattr(user, 'has_perm'):
                return False, "Invalid user object provided"

            if not user.has_perm('sales.can_fiscalize_sales'):
                return False, "User does not have permission to fiscalize sales"

        # Customer validation for B2B/B2G
        if self.customer:
            customer_type = getattr(self.customer, 'customer_type', None)
            if customer_type in ['BUSINESS', 'GOVERNMENT']:
                if not getattr(self.customer, 'tin', None):
                    return False, f"{customer_type} customers must have a TIN for fiscalization"

        if self.is_export_invoice():
            export_errors = self.validate_export_invoice()
            if export_errors:
                error_summary = f"Export validation failed: {'; '.join(export_errors[:3])}"
                if len(export_errors) > 3:
                    error_summary += f" (and {len(export_errors) - 3} more errors)"
                return False, error_summary

        return True, "Sale can be fiscalized"

    def get_efris_basic_info(self):
        """Get basic information for EFRIS - works for ALL sales with VAT-aware invoiceKind and export support"""

        # Get company VAT status from store
        company = self.store.company if self.store else None
        is_vat_enabled = getattr(company, 'is_vat_enabled', False) if company else False

        # Determine if this is an export invoice
        is_export = self.is_export_invoice()

        # Invoice kind based on VAT status
        if is_vat_enabled:
            efris_invoice_kind = '1'  # Tax Invoice
            efris_invoice_type = '1'  # Tax Invoice
        else:
            efris_invoice_kind = '2'  # Simplified Invoice/Receipt
            efris_invoice_type = '1'  # Simplified Invoice

        # Industry code: 101=Domestic, 102=Export
        invoice_industry_code = '102' if is_export else '101'

        basic_info = {
            "invoiceNo": "",
            "issuedDate": self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            "operator": getattr(self, 'operator_name', None) or (
                self.created_by.get_full_name() if self.created_by else 'System'
            ),
            "currency": self.currency or 'UGX',
            "invoiceType": efris_invoice_type,
            "invoiceKind": efris_invoice_kind,
            "dataSource": "103",  # Electronic system
            "invoiceIndustryCode": invoice_industry_code,  # ✅ NEW: Export support
        }

        # ✅ NEW: Add deliveryTermsCode for exports (MANDATORY)
        if is_export:
            delivery_terms = getattr(self, 'delivery_terms_code', None) or getattr(self, 'export_delivery_terms', None)
            if not delivery_terms:
                logger.warning(f"Export sale {self.id} missing deliveryTermsCode, using FOB as default")
                delivery_terms = "FOB"
            basic_info["deliveryTermsCode"] = delivery_terms

        logger.info(
            f"EFRIS Invoice Kind for {self.document_number}: "
            f"invoiceKind={efris_invoice_kind}, "
            f"invoiceType={efris_invoice_type}, "
            f"invoiceIndustryCode={invoice_industry_code}, "
            f"VAT Enabled={is_vat_enabled}, "
            f"Is Export={is_export}"
        )

        return basic_info

    def get_efris_summary(self):
        """Get summary information for EFRIS - works for ALL sales"""
        net_amount = self.subtotal - (self.discount_amount or 0)

        return {
            "netAmount": str(net_amount),
            "taxAmount": str(self.tax_amount or 0),
            "grossAmount": str(self.total_amount),
            "itemCount": str(self.item_count),
            "modeCode": "1",  # 1=Real-time, 2=Batch
            "remarks": self.notes or f"{self.get_document_type_display()} processed via system"
        }

    def get_efris_goods_details(self):
        """Get goods/services details for EFRIS - supports export fields"""
        goods_details = []

        # Check if this is an export invoice
        is_export = self.is_export_invoice()

        for idx, item in enumerate(self.items.select_related('product', 'service').all(), 1):
            # Determine if it's a product or service
            is_product = item.product is not None

            if is_product:
                item_name = item.product.name
                item_code = item.product.efris_goods_code
                unit_measure = getattr(item.product, 'unit_of_measure', 'U')

                # Get EFRIS product data
                product_efris_data = {}
                if hasattr(item.product, 'get_efris_goods_data'):
                    try:
                        product_efris_data = item.product.get_efris_goods_data()
                    except:
                        pass

                if item.product.category:
                    category_id = item.product.category.efris_commodity_category_code
                    category_name = product_efris_data.get('efris_commodity_category_name', 'General Goods')
                else:
                    category_id = "101113010000000000"
                    category_name = "General Goods"
            else:
                # Service
                item_name = item.service.name
                item_code = item.service.efris_service_code
                unit_measure = getattr(item.service, 'unit_of_measure', '207')

                service_efris_data = {}
                if hasattr(item.service, 'get_efris_data'):
                    try:
                        service_efris_data = item.service.get_efris_data()
                    except:
                        pass

                if item.service.category:
                    category_id = item.service.category.efris_commodity_category_code
                    category_name = service_efris_data.get('efris_commodity_category_name', 'General Services')
                else:
                    category_id = "100000000000000000"
                    category_name = "General Services"

            goods_detail = {
                "item": item_name,
                "itemCode": item_code,
                "qty": str(item.quantity),
                "unitOfMeasure": unit_measure,
                "unitPrice": str(item.unit_price),
                "total": str(item.total_price),
                "taxRate": self._get_efris_tax_rate_string(item.tax_rate),
                "tax": str(item.tax_amount or 0),
                "orderNumber": str(idx),
                "discountFlag": "1" if (item.discount_amount or 0) > 0 else "2",
                "deemedFlag": "2",
                "exciseFlag": "2",
                "goodsCategoryId": category_id,
                "goodsCategoryName": category_name
            }

            if item.discount_amount and item.discount_amount > 0:
                goods_detail["discountTotal"] = str(item.discount_amount)

            # ✅ NEW: Add export-specific fields for products
            if is_export and is_product:
                # HS Code (MANDATORY for exports)
                hs_code = getattr(item.product, 'hs_code', '') or ''
                hs_name = getattr(item.product, 'hs_name', '') or ''

                if hs_code:
                    goods_detail["hsCode"] = str(hs_code)[:50]
                if hs_name:
                    goods_detail["hsName"] = str(hs_name)[:1000]

                # Total weight (MANDATORY for exports)
                total_weight = getattr(item, 'export_total_weight', None)
                if total_weight:
                    goods_detail["totalWeight"] = f"{total_weight:.2f}"
                else:
                    logger.warning(f"Export item {idx} missing totalWeight")
                    goods_detail["totalWeight"] = "0.00"

                # Piece quantity (MANDATORY for exports)
                piece_qty = getattr(item, 'export_piece_qty', None)
                if piece_qty:
                    goods_detail["pieceQty"] = f"{piece_qty:.2f}"
                else:
                    logger.warning(f"Export item {idx} missing pieceQty")
                    goods_detail["pieceQty"] = "0.00"

                # Piece measure unit (MANDATORY for exports)
                piece_measure_unit = getattr(item, 'export_piece_measure_unit', '')
                if piece_measure_unit:
                    goods_detail["pieceMeasureUnit"] = piece_measure_unit
                else:
                    logger.warning(f"Export item {idx} missing pieceMeasureUnit")
                    goods_detail["pieceMeasureUnit"] = unit_measure  # Fallback to main unit

            goods_details.append(goods_detail)

        return goods_details

    def get_efris_payment_details(self):
        """Get payment details for EFRIS - works for ALL sales"""
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
            # For receipts: immediate payment, for invoices: might be credit
            payment_mode = self._get_efris_payment_mode(self.payment_method)
            payment_details.append({
                "paymentMode": payment_mode,
                "paymentAmount": str(self.total_amount),
                "orderNumber": "a"
            })

        return payment_details

    def validate_export_invoice(self):
        """Validate export invoice requirements per T109 spec"""
        errors = []

        if not self.is_export_invoice():
            return errors  # Not an export

        # MANDATORY: deliveryTermsCode
        valid_incoterms = ['CFR', 'CIF', 'CIP', 'CPT', 'DAP', 'DDP',
                           'DPU', 'EXW', 'FAS', 'FCA', 'FOB']
        delivery_terms = getattr(self, 'delivery_terms_code', None) or getattr(self, 'export_delivery_terms', None)

        if not delivery_terms:
            errors.append("deliveryTermsCode MANDATORY for export invoices")
        elif delivery_terms not in valid_incoterms:
            errors.append(f"Invalid Incoterms: {delivery_terms}. Must be one of: {', '.join(valid_incoterms)}")

        # Validate each item has export fields
        for idx, item in enumerate(self.items.all(), 1):
            if item.item_type == 'PRODUCT' and item.product:
                # HS Code
                if not getattr(item.product, 'hs_code', None):
                    errors.append(f"Item {idx} ({item.product.name}): HS Code MANDATORY for export")

                # Total Weight
                if not getattr(item, 'export_total_weight', None) or item.export_total_weight <= 0:
                    errors.append(f"Item {idx} ({item.product.name}): totalWeight MANDATORY for export")

                # Piece Quantity
                if not getattr(item, 'export_piece_qty', None) or item.export_piece_qty <= 0:
                    errors.append(f"Item {idx} ({item.product.name}): pieceQty MANDATORY for export")

                # Piece Measure Unit
                if not getattr(item, 'export_piece_measure_unit', None):
                    errors.append(f"Item {idx} ({item.product.name}): pieceMeasureUnit MANDATORY for export")

        return errors

    def _get_efris_tax_rate_string(self, tax_rate_code):
        """Convert tax rate code to EFRIS string value"""
        tax_rate_mapping = {
            'A': '0.18',  # Standard VAT 18%
            'B': '0.00',  # Zero rate
            'C': '-',  # Exempt
            'D': '0.18',  # Deemed rate
            'E': '0.18',  # Excise duty
        }
        return tax_rate_mapping.get(str(tax_rate_code).upper(), '0.18')

    def _get_efris_payment_mode(self, payment_method):
        """Map payment method to EFRIS payment mode"""
        payment_modes = {
            'CASH': '102',  # Cash
            'CARD': '106',  # Credit/Debit Card
            'MOBILE_MONEY': '105',  # Mobile Money
            'BANK_TRANSFER': '107',  # Bank Transfer
            'VOUCHER': '101',  # Voucher/Coupon
            'CREDIT': '101',  # Credit sale
        }
        return payment_modes.get(payment_method.upper(), '102')

    def get_efris_invoice_data(self):
        """Get complete invoice data formatted for EFRIS API - works for ALL sales"""
        # Use Sale's EFRIS mixin methods to build data
        seller_details = self.store.company.get_efris_seller_details() if hasattr(self.store.company,
                                                                                  'get_efris_seller_details') else self._get_default_seller_details()

        buyer_details = {}
        if self.customer and hasattr(self.customer, 'get_efris_buyer_details'):
            buyer_details = self.customer.get_efris_buyer_details()
        else:
            buyer_details = self._get_default_buyer_details()

        basic_info = self.get_efris_basic_info()
        goods_details = self.get_efris_goods_details()
        summary = self.get_efris_summary()
        payment_details = self.get_efris_payment_details()

        # Build tax details
        tax_details = self._build_efris_tax_details()

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
        company = self.store.company
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
        customer = self.customer

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

    def _build_efris_tax_details(self):
        """Build tax details for EFRIS"""
        net_amount = self.subtotal - (self.discount_amount or 0)

        # Group items by tax rate
        tax_groups = {}
        for item in self.items.all():
            tax_rate = self._get_efris_tax_rate_string(item.tax_rate)
            item_net = item.total_price - (item.discount_amount or 0)

            if tax_rate not in tax_groups:
                tax_groups[tax_rate] = {
                    'net_amount': Decimal('0'),
                    'tax_amount': Decimal('0'),
                }

            tax_groups[tax_rate]['net_amount'] += item_net
            tax_groups[tax_rate]['tax_amount'] += (item.tax_amount or Decimal('0'))

        tax_details = []
        for tax_rate, amounts in tax_groups.items():
            if tax_rate == '-':  # Exempt
                tax_category = "03"
                tax_rate_display = "0.00"
            elif tax_rate == '0.00':  # Zero rate
                tax_category = "02"
                tax_rate_display = "0.00"
            else:  # Standard rate
                tax_category = "01"
                tax_rate_display = tax_rate

            tax_details.append({
                "taxCategoryCode": tax_category,
                "netAmount": str(amounts['net_amount']),
                "taxRate": tax_rate_display,
                "taxAmount": str(amounts['tax_amount']),
                "grossAmount": str(amounts['net_amount'] + amounts['tax_amount']),
                "taxRateName": {
                    '0.18': 'Standard Rate (18%)',
                    '0.00': 'Zero Rate (0%)',
                    '-': 'Exempt'
                }.get(tax_rate, 'Standard Rate')
            })

        return tax_details


from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from django.utils.translation import gettext_lazy as _
import uuid
import logging
from primebooks.mixins import OfflineIDMixin


logger = logging.getLogger(__name__)


class Sale(OfflineIDMixin, models.Model, EFRISSaleMixin):
    # ==================== NEW: Document Type System ====================
    DOCUMENT_TYPE_CHOICES = [
        ('RECEIPT', 'Receipt'),
        ('INVOICE', 'Invoice'),
        ('PROFORMA', 'Proforma/Quotation'),
        ('ESTIMATE', 'Estimate'),
    ]

    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPE_CHOICES,
        default='RECEIPT',
        db_index=True
    )

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

    # ==================== NEW: Enhanced Status System ====================
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING_PAYMENT', 'Pending Payment'),
        ('PARTIALLY_PAID', 'Partially Paid'),
        ('PAID', 'Paid'),
        ('COMPLETED', 'Completed'),
        ('OVERDUE', 'Overdue'),
        ('VOIDED', 'Voided'),
        ('REFUNDED', 'Refunded'),
        ('CANCELLED', 'Cancelled'),
    ]

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT'
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True,
    )
    # ==================== NEW: Payment Status ====================
    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending Payment'),
        ('PARTIALLY_PAID', 'Partially Paid'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
        ('NOT_APPLICABLE', 'Not Applicable'),
    ]

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='PENDING'
    )

    transaction_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # ==================== CHANGED: document_number replaces invoice_number ====================
    document_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        unique=True,
        db_index=True,
        verbose_name="Document Number"
    )

    store = models.ForeignKey('stores.Store', on_delete=models.PROTECT, related_name='sales')
    created_by = models.ForeignKey('accounts.CustomUser', on_delete=models.PROTECT, related_name='created_sales')
    customer = models.ForeignKey('customers.Customer', on_delete=models.SET_NULL, null=True, blank=True)

    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, default='SALE')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='CASH')
    currency = models.CharField(max_length=3, default='UGX')

    # ==================== NEW: Due Date for Invoices ====================
    due_date = models.DateField(null=True, blank=True, verbose_name="Due Date")

    # ✅ CHANGED: Removed MinValueValidator to allow negative values for refunds
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Add discount percentage field (keep validator for percentage)
    discount = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )

    # EFRIS
    efris_invoice_number = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    verification_code = models.CharField(max_length=100, blank=True, null=True)
    qr_code = models.TextField(blank=True, null=True)
    is_fiscalized = models.BooleanField(default=False, db_index=True)
    fiscalization_time = models.DateTimeField(blank=True, null=True)
    fiscal_number = models.CharField(max_length=64, blank=True, null=True)
    fiscalization_status = models.CharField(max_length=32, blank=True, null=True, default='pending')
    fiscalization_error = models.TextField(blank=True, null=True)
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
    # Export invoice fields
    export_buyer_country = models.CharField(max_length=100, blank=True, null=True)
    export_buyer_passport = models.CharField(max_length=50, blank=True, null=True)
    export_currency = models.CharField(max_length=3, default='UGX')
    export_exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)

    # T109 Export Invoice Support
    is_export_sale = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Export Sale"),
        help_text=_("Sale is an export invoice (invoiceIndustryCode=102)")
    )

    invoice_industry_code = models.CharField(
        max_length=3,
        default='101',
        verbose_name=_("Invoice Industry Code"),
        help_text=_("101=Domestic, 102=Export")
    )

    delivery_terms_code = models.CharField(
        max_length=3,
        blank=True,
        verbose_name=_("Delivery Terms (Incoterms)"),
        help_text=_("MANDATORY for exports: FOB, CIF, CFR, CPT, DAP, DDP, etc.")
    )


    # Void tracking
    is_refunded = models.BooleanField(default=False)
    is_voided = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True, null=True)
    void_notes = models.TextField(blank=True, null=True)
    voided_at = models.DateTimeField(blank=True, null=True)
    voided_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='voided_sales'
    )

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
            models.Index(fields=['store', 'status', 'created_at']),
            models.Index(fields=['document_type']),
            models.Index(fields=['document_number']),
            models.Index(fields=['payment_status']),
            models.Index(fields=['due_date']),
            models.Index(fields=['export_status']),
        ]
        verbose_name = "Sale"
        verbose_name_plural = "Sales"
        # ✅ REMOVED: Constraints that enforce positive values

    def __str__(self):
        doc_type = self.get_document_type_display()
        prefix = "REFUND: " if self.transaction_type == 'REFUND' else ""
        return f"{prefix}{doc_type} #{self.document_number or self.transaction_id}"

    def clean(self):
        """Model-level validation - handles both sales and refunds"""
        super().clean()

        # Convert to Decimal explicitly
        subtotal = Decimal(str(self.subtotal or 0))
        tax = Decimal(str(self.tax_amount or 0))
        discount = Decimal(str(self.discount_amount or 0))
        total = Decimal(str(self.total_amount or 0))

        # ✅ CHANGED: Validation based on transaction type
        if self.transaction_type == 'SALE':
            # For sales: total should equal subtotal - discount
            calculated_total = subtotal - discount

            if abs(total - calculated_total) > Decimal('0.01'):
                raise ValidationError("Total amount doesn't match calculated total")

            # Validate discount doesn't exceed subtotal for sales
            if discount > subtotal:
                raise ValidationError("Discount amount cannot exceed subtotal")

            # Validate amounts are positive for sales
            if subtotal < 0 or total < 0:
                raise ValidationError("Sale amounts must be positive")

        elif self.transaction_type == 'REFUND':
            # For refunds: amounts should be negative or zero
            if total > 0:
                raise ValidationError("Refund total amount must be negative or zero")

        # Validate due date for invoices
        if self.document_type == 'INVOICE' and self.transaction_type == 'SALE' and not self.due_date:
            raise ValidationError("Due date is required for invoices")

        # Validate payment status based on document type
        if self.document_type == 'RECEIPT' and self.transaction_type == 'SALE' and self.payment_status != 'PAID':
            self.payment_status = 'PAID'

    def is_export_invoice(self):
        """
        Helper method to check if this is an export invoice.
        Export invoices are regular invoices with invoice_industry_code='102'
        """
        return (
                self.document_type == 'INVOICE' and
                (self.invoice_industry_code == '102' or self.is_export_sale)
        )

    def validate_export_invoice(self):
        """Validate export invoice requirements per T109 spec"""
        errors = []

        if not self.is_export_invoice():
            return errors

        # MANDATORY: deliveryTermsCode
        valid_incoterms = ['CFR', 'CIF', 'CIP', 'CPT', 'DAP', 'DDP',
                           'DPU', 'EXW', 'FAS', 'FCA', 'FOB']
        if not self.delivery_terms_code:
            errors.append("deliveryTermsCode MANDATORY for export invoices")
        elif self.delivery_terms_code not in valid_incoterms:
            errors.append(f"Invalid Incoterms: {self.delivery_terms_code}")

        # Validate each item has export fields
        for idx, item in enumerate(self.items.all(), 1):
            if item.item_type == 'PRODUCT':
                if not item.product.hs_code:
                    errors.append(f"Item {idx}: HS Code MANDATORY for export")
                if not item.export_total_weight or item.export_total_weight <= 0:
                    errors.append(f"Item {idx}: totalWeight MANDATORY for export")
                if not item.export_piece_qty or item.export_piece_qty <= 0:
                    errors.append(f"Item {idx}: pieceQty MANDATORY for export")
                if not item.export_piece_measure_unit:
                    errors.append(f"Item {idx}: pieceMeasureUnit MANDATORY for export")

        return errors

    @property
    def efris_invoice_industry_code(self):
        """Get EFRIS invoiceIndustryCode"""
        if self.is_export_invoice():
            return '102'
        return '101'

    def save(self, *args, **kwargs):
        # Auto-generate document number based on type
        if not self.document_number:
            self.document_number = self.generate_document_number()

        # Set appropriate status and payment status based on document type
        if self.transaction_type != 'REFUND':
            self.set_auto_statuses()

        # Calculate total if not set
        if not self.total_amount or self.total_amount == 0:
            subtotal = Decimal(str(self.subtotal or 0))
            discount = Decimal(str(self.discount_amount or 0))
            calculated_total = subtotal - discount
            self.total_amount = calculated_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Run model validation
        self.full_clean()

        is_new = not self.pk

        super().save(*args, **kwargs)

        # ✅ CHANGED: Only create invoice/receipt for non-refund transactions
        if self.transaction_type != 'REFUND':
            if self.document_type == 'INVOICE' and self.customer:
                self.customer.update_credit_balance()
                if not hasattr(self, 'invoice_detail') or self.invoice_detail is None:
                    try:
                        from invoices.models import Invoice as InvoiceModel

                        business_type = 'B2C'
                        if self.customer:
                            if hasattr(self.customer, 'customer_type'):
                                if self.customer.customer_type == 'BUSINESS':
                                    business_type = 'B2B'
                                elif self.customer.customer_type in ['GOVERNMENT', 'PUBLIC']:
                                    business_type = 'B2G'
                            elif hasattr(self.customer, 'tin') and self.customer.tin:
                                business_type = 'B2B'

                        invoice, created = InvoiceModel.objects.get_or_create(
                            sale=self,
                            defaults={
                                'store': self.store,
                                'terms': '',
                                'purchase_order': '',
                                'created_by': self.created_by,
                                'business_type': business_type,
                                'operator_name': self.created_by.get_full_name() if self.created_by else 'System',
                                'fiscalization_status': 'pending',
                                'efris_document_type': '1',
                                'auto_fiscalize': True,
                            }
                        )
                        if created:
                            logger.info(f"✅ Auto-created Invoice record for sale {self.document_number}")
                        else:
                            logger.debug(f"ℹ️  Invoice already exists for sale {self.document_number}, skipping")
                    except Exception as e:
                        logger.error(f"❌ Failed to auto-create Invoice record for sale {self.id}: {e}", exc_info=True)

            if self.document_type == 'RECEIPT' and is_new:
                try:
                    from sales.models import Receipt as ReceiptModel
                    receipt, created = ReceiptModel.objects.get_or_create(
                        sale=self,
                        defaults={
                            'receipt_number': self.document_number,
                            'printed_by': self.created_by,
                            'receipt_data': {
                                'items': [],
                                'totals': {
                                    'subtotal': str(self.subtotal),
                                    'tax': str(self.tax_amount),
                                    'discount': str(self.discount_amount),
                                    'total': str(self.total_amount),
                                }
                            }
                        }
                    )
                    if created:
                        logger.info(f"✅ Auto-created Receipt record for sale {self.document_number}")
                    else:
                        logger.debug(f"ℹ️  Receipt already exists for sale {self.document_number}, skipping")
                except Exception as e:
                    logger.error(f"❌ Failed to auto-create Receipt record: {e}", exc_info=True)

        # Send WebSocket update
        if self.status in ['COMPLETED', 'PAID']:
            try:
                self.send_sale_update()
            except Exception as e:
                logger.error(f"WebSocket update failed for sale {self.id}: {e}")

        # Auto-fiscalize if needed (not for refunds)
        if is_new and self.status in ['COMPLETED', 'PAID'] and self.transaction_type != 'REFUND':
            # ✅ CHANGED: Skip if caller explicitly deferred fiscalization
            # (e.g. process_sale_creation — items don't exist yet at this point)
            if getattr(self, '_defer_auto_fiscalize', False):
                logger.info(
                    f"Auto-fiscalization deferred for sale {self.id} "
                    f"— will be triggered after items are created"
                )
            else:
                try:
                    store_config = self.store.effective_efris_config
                    if store_config.get('enabled', False) and store_config.get('is_active', False):
                        auto_fiscalize = store_config.get('auto_fiscalize_sales', True)
                        if auto_fiscalize:
                            from django.db import transaction
                            if not transaction.get_autocommit():
                                transaction.on_commit(lambda: self._auto_fiscalize_sale())
                            else:
                                self._auto_fiscalize_sale()
                except Exception as e:
                    logger.error(f"Auto-fiscalization check failed for sale {self.id}: {e}")

    def generate_document_number(self):
        """Generate unique document number — race-condition safe."""
        from django.db import transaction as _tx

        if self.transaction_type == 'REFUND':
            prefix = 'REF'
        else:
            prefix = {
                'RECEIPT': 'RCP',
                'INVOICE': 'INV',
                'PROFORMA': 'PRO',
                'ESTIMATE': 'EST',
            }.get(self.document_type, 'SAL')

        date_str = timezone.now().strftime('%Y%m%d')
        today = timezone.now().date()

        # Retry loop handles the rare case where two concurrent sales grab
        # the same sequence number. Max 10 attempts is more than enough.
        for attempt in range(10):
            # Count existing docs of this type today to determine next sequence
            count = Sale.objects.filter(
                document_type=self.document_type,
                transaction_type=self.transaction_type,
                created_at__date=today,
            ).exclude(pk=self.pk).count()

            sequence = count + 1 + attempt  # attempt bumps sequence on collision
            candidate = f"{prefix}-{date_str}-{sequence:04d}"

            # Check if candidate is already taken
            if not Sale.objects.filter(document_number=candidate).exists():
                return candidate

        # Absolute fallback — use microseconds to guarantee uniqueness
        import time
        return f"{prefix}-{date_str}-{int(time.time() * 1000) % 100000:05d}"

    def update_totals(self):
        """Update totals using SaleItems - handles both sales and refunds"""
        from django.db.models import Sum

        aggregates = self.items.aggregate(
            subtotal_sum=Sum('total_price'),
            discount_sum=Sum('discount_amount'),
            tax_sum=Sum('tax_amount')
        )

        # Convert to Decimal explicitly
        subtotal = Decimal(str(aggregates['subtotal_sum'] or 0))
        discount = Decimal(str(aggregates['discount_sum'] or 0))
        tax = Decimal(str(aggregates['tax_sum'] or 0))

        self.subtotal = subtotal
        self.discount_amount = discount
        self.tax_amount = tax

        # ✅ CHANGED: Handle both positive (sales) and negative (refunds) totals
        if self.transaction_type == 'REFUND':
            # For refunds: all values are negative, so add them
            self.total_amount = (subtotal + discount + tax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            # For sales: normal calculation
            self.total_amount = (subtotal - discount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            # Ensure total_amount is not negative for sales
            if self.total_amount < 0:
                self.total_amount = Decimal('0')

        self.save(update_fields=['subtotal', 'tax_amount', 'discount_amount', 'total_amount'])

    @property
    def is_completed(self):
        """Backward compatibility property"""
        return self.status in ['COMPLETED', 'PAID']

    @property
    def is_paid(self):
        """Check if sale is paid"""
        return self.payment_status == 'PAID'

    def send_sale_update(self):
        """Send WebSocket message for real-time updates per store"""
        if not hasattr(self, '_websocket_sent'):
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync

                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f'sales_{self.store.id}',
                        {
                            'type': 'sale_update',
                            'message': {
                                'sale_id': str(self.id),
                                'document_number': self.document_number,
                                'document_type': self.document_type,
                                'transaction_type': self.transaction_type,
                                'status': self.status,
                                'payment_status': self.payment_status,
                                'total_amount': str(self.total_amount),
                                'store_id': self.store.id,
                                'created_at': self.created_at.isoformat(),
                            }
                        }
                    )
                    self._websocket_sent = True
            except Exception as e:
                logger.error(f"WebSocket Error for Sale {self.id}: {e}")

    # ==================== Helper Properties ====================
    @property
    def item_count(self):
        return self.items.count()

    @property
    def is_receipt(self):
        return self.document_type == 'RECEIPT'

    @property
    def is_invoice(self):
        return self.document_type == 'INVOICE'

    @property
    def is_proforma(self):
        return self.document_type == 'PROFORMA'

    @property
    def is_estimate(self):
        return self.document_type == 'ESTIMATE'

    @property
    def days_overdue(self):
        """Calculate days overdue for invoices"""
        if not self.due_date or self.payment_status == 'PAID':
            return 0
        return max(0, (timezone.now().date() - self.due_date).days)

    @property
    def amount_paid(self):
        """Total amount paid for this sale"""
        return self.payments.aggregate(total=models.Sum('amount'))['total'] or 0

    @property
    def amount_outstanding(self):
        """Outstanding amount to be paid"""
        if self.document_type != 'INVOICE':
            return Decimal('0')
        return max(Decimal('0'), self.total_amount - self.amount_paid)

    @property
    def issue_date(self):
        """Provide issue_date for EFRIS compatibility"""
        return self.created_at

    @property
    def fiscal_document_number(self):
        """Provide fiscal_document_number for EFRIS compatibility"""
        return self.efris_invoice_number

    @fiscal_document_number.setter
    def fiscal_document_number(self, value):
        """Set fiscal_document_number for EFRIS compatibility"""
        self.efris_invoice_number = value

    @property
    def company(self):
        """Get company from store for EFRIS"""
        return self.store.company

    @property
    def invoice_number(self):
        """Backward compatibility property for invoice_number"""
        return self.document_number

    @property
    def receipt_number(self):
        """Get receipt number if available"""
        if hasattr(self, 'receipt_detail') and self.receipt_detail:
            return self.receipt_detail.receipt_number
        return self.document_number

    @property
    def total_quantity(self):
        from django.db.models import Sum
        result = self.items.aggregate(total=Sum('quantity'))
        return result['total'] or 0

    def update_from_efris_response(self, response_data):
        """Update sale with EFRIS fiscalization response data"""
        try:
            if not response_data:
                logger.warning(f"No EFRIS response data provided for sale {self.id}")
                return

            updates = {}

            basic_info = response_data.get('basicInformation', {})
            summary = response_data.get('summary', {})
            data_section = response_data.get('data', {})

            fiscal_doc_number = (
                    basic_info.get('invoiceNo')
                    or response_data.get('invoiceNo')
                    or data_section.get('invoiceNo')
            )
            if fiscal_doc_number:
                updates['efris_invoice_number'] = fiscal_doc_number

            verification_code = (
                    basic_info.get('antifakeCode')
                    or response_data.get('antifakeCode')
                    or data_section.get('antifakeCode')
            )
            if verification_code:
                updates['verification_code'] = verification_code

            qr_code = (
                    summary.get('qrCode')
                    or summary.get('qr_code')
                    or response_data.get('qrCode')
                    or response_data.get('qr_code')
                    or response_data.get('full_response', {}).get('summary', {}).get('qrCode')
            )
            if qr_code:
                self.qr_code = qr_code
                updates['qr_code'] = qr_code

            updates['is_fiscalized'] = True
            updates['fiscalization_time'] = timezone.now()

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
        if not self.is_invoice:
            logger.warning(f"Sale {self.id} is not an invoice, cannot process for EFRIS")
            return None

        if hasattr(self, 'invoice_detail') and self.invoice_detail:
            return self.invoice_detail

        return self

    def mark_fiscalization_failed(self, error_message):
        """Mark sale fiscalization as failed"""
        self.fiscalization_error = error_message
        self.fiscalization_status = 'failed'
        self.save(update_fields=['fiscalization_error', 'fiscalization_status'])

    def update_payment_status(self):
        """Update payment status based on payments"""
        from django.db.models import Sum
        from decimal import Decimal

        total_paid = self.payments.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        total_amount = Decimal(str(self.total_amount or 0))
        total_paid = Decimal(str(total_paid))

        # Determine status
        if total_paid >= total_amount:
            self.payment_status = 'PAID'  # ✅ Use 'PAID' not 'COMPLETED'
            if self.status != 'CANCELLED':
                self.status = 'COMPLETED'  # ✅ This is correct (status field)
        elif total_paid > Decimal('0'):
            self.payment_status = 'PARTIALLY_PAID'
            if self.status == 'DRAFT':
                self.status = 'PENDING_PAYMENT'
        else:
            self.payment_status = 'PENDING'

        # Check overdue
        if self.payment_status in ['PENDING', 'PARTIALLY_PAID']:
            if self.due_date and self.due_date < timezone.now().date():
                self.payment_status = 'OVERDUE'

        self.save(update_fields=['payment_status', 'status'])

        logger.info(
            f"Updated sale {self.id} payment status to {self.payment_status}, "
            f"status to {self.status}"
        )

    def calculate_payment_status(self):
        """Calculate payment status without saving"""
        from django.db.models import Sum
        from decimal import Decimal

        total_paid = self.payments.filter(is_confirmed=True).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        total_amount = self.total_amount or Decimal('0')

        if total_paid >= total_amount:
            return 'PAID'
        elif total_paid > 0:
            return 'PARTIALLY_PAID'
        elif self.document_type == 'INVOICE' and self.due_date:
            today = timezone.now().date()
            if self.due_date < today:
                return 'OVERDUE'

        return 'PENDING'

    def create_stock_movements_for_efris(self):
        """Create comprehensive stock movements for EFRIS audit trail"""
        try:
            from inventory.models import StockMovement

            for item in self.items.select_related('product'):
                # Skip services (they don't have stock)
                if item.item_type != 'PRODUCT' or not item.product:
                    continue

                movement_reference = self.efris_invoice_number or self.document_number or f"SALE-{self.id}"

                StockMovement.objects.create(
                    product=item.product,
                    store=self.store,
                    movement_type='SALE',
                    quantity=abs(item.quantity),  # Use absolute value
                    reference=movement_reference,
                    unit_price=item.unit_price,
                    total_value=abs(item.total_price),
                    created_by=self.created_by,
                    notes=f'EFRIS Sale: {movement_reference}' if self.is_fiscalized else f'Sale: {movement_reference}',
                    efris_reference=self.efris_invoice_number if self.is_fiscalized else None,
                    fiscal_document_number=self.efris_invoice_number if self.is_fiscalized else None
                )

            return True
        except Exception as e:
            logger.error(f"Error creating EFRIS stock movements for sale {self.id}: {e}")
            return False

    def set_auto_statuses(self):
        """Set status and payment status based on document type and payment"""
        if self.document_type == 'RECEIPT':
            self.payment_status = 'PAID'  # ✅ Correct
            self.status = 'COMPLETED'  # ✅ Correct (status, not payment_status)
        elif self.document_type == 'INVOICE':
            if self.payment_method == 'CREDIT':
                self.payment_status = 'PENDING'
                self.status = 'PENDING_PAYMENT'
            else:
                self.payment_status = 'PAID'  # ✅ Changed from 'COMPLETED' to 'PAID'
                self.status = 'COMPLETED'
        elif self.document_type in ['PROFORMA', 'ESTIMATE']:
            self.payment_status = 'NOT_APPLICABLE'
            self.status = 'DRAFT'

    def convert_to_invoice(self, due_date=None, terms=None):
        """Convert a proforma/estimate to an invoice"""
        if self.document_type not in ['PROFORMA', 'ESTIMATE']:
            raise ValidationError("Only proforma and estimates can be converted to invoices")

        invoice_sale = Sale.objects.create(
            store=self.store,
            created_by=self.created_by,
            customer=self.customer,
            document_type='INVOICE',
            payment_method='CREDIT',
            due_date=due_date or (timezone.now().date() + timedelta(days=30)),
            subtotal=self.subtotal,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            total_amount=self.total_amount,
            currency=self.currency,
            notes=f"Converted from {self.document_type.lower()} #{self.document_number}",
            duplicated_from=self
        )

        # Copy items
        for item in self.items.all():
            from sales.models import SaleItem
            SaleItem.objects.create(
                sale=invoice_sale,
                item_type=item.item_type,
                product=item.product,
                service=item.service,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_price=item.total_price,
                tax_rate=item.tax_rate,
                tax_amount=item.tax_amount,
                discount=item.discount,
                discount_amount=item.discount_amount,
                description=item.description
            )

        invoice_sale.update_totals()

        from invoices.models import Invoice
        Invoice.objects.create(
            sale=invoice_sale,
            store=self.store,
            terms=terms or '',
            purchase_order='',
            created_by=self.created_by
        )

        return invoice_sale

    def fiscalize_and_sync_stock(self):
        """Mark sale as fiscalized and sync related stock movements to EFRIS"""
        try:
            from inventory.models import StockMovement

            if not self.is_fiscalized:
                self.is_fiscalized = True
                self.fiscalization_time = timezone.now()
                self.save(update_fields=['is_fiscalized', 'fiscalization_time'])

            movements = StockMovement.objects.filter(
                reference__icontains=self.document_number,
                store=self.store,
                synced_to_efris=False
            )

            synced_count = 0
            for movement in movements:
                if movement.sync_to_efris_now():
                    synced_count += 1

            logger.info(
                f"✅ Fiscalized sale {self.document_number} and queued "
                f"{synced_count} stock movements for EFRIS sync"
            )

            return True

        except Exception as e:
            logger.error(f"Error in fiscalize_and_sync_stock for sale {self.id}: {e}")
            return False

    def _auto_fiscalize_sale(self):
        """Auto-fiscalize sale after creation"""
        try:
            if self.is_fiscalized:
                return

            can_fiscalize, reason = self.can_fiscalize()
            if not can_fiscalize:
                logger.warning(f"Cannot auto-fiscalize sale {self.id}: {reason}")
                return

            from .tasks import fiscalize_invoice_async
            fiscalize_invoice_async.delay(
                self.id,
                user_id=getattr(self.created_by, 'pk', None)
            )

            logger.info(f"Queued sale {self.document_number} for auto-fiscalization")

        except Exception as e:
            logger.error(f"Error in auto-fiscalization for sale {self.id}: {e}")

    def _create_invoice_if_needed(self):
        """Create invoice for EFRIS fiscalization if needed"""
        try:
            if not self.total_amount or self.total_amount <= 0:
                logger.warning(f"Skipping invoice creation for sale {self.id} - zero or negative amount")
                return None

            store_config = self.store.effective_efris_config

            if (store_config.get('enabled', False) and
                    store_config.get('auto_fiscalize_sales', False) and
                    self.status in ['COMPLETED', 'PAID']):

                from invoices.models import Invoice

                business_type = (
                    self._determine_business_type()
                    if hasattr(self, '_determine_business_type')
                    else 'B2C'
                )

                invoice, created = Invoice.objects.get_or_create(
                    sale=self,
                    defaults={
                        'store': self.store,
                        'terms': '',
                        'purchase_order': '',
                        'business_type': business_type,
                        'operator_name': self.created_by.get_full_name() if self.created_by else 'System',
                        'created_by': self.created_by,
                        'auto_fiscalize': True,
                    }
                )

                if created:
                    logger.info(f"✅ Created invoice {invoice.id} for sale {self.id}")
                else:
                    logger.info(f"ℹ️  Invoice already exists for sale {self.id} (id={invoice.id}), skipping")

                return invoice

            return None

        except Exception as e:
            logger.error(f"❌ Error creating invoice for sale {self.id}: {e}", exc_info=True)
            return None


class SaleItem(OfflineIDMixin, models.Model):
    TAX_RATE_CHOICES = [
        ('A', 'Standard rate (18%)'),
        ('B', 'Zero rate (0%)'),
        ('C', 'Exempt (Not taxable)'),
        ('D', 'Deemed rate (18%)'),
        ('E', 'Excise Duty rate (per product)'),
    ]

    ITEM_TYPE_CHOICES = [
        ('PRODUCT', 'Product'),
        ('SERVICE', 'Service'),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True,
    )
    sale = models.ForeignKey('Sale', related_name='items', on_delete=models.CASCADE)
    item_type = models.CharField(
        max_length=10,
        choices=ITEM_TYPE_CHOICES,
        default='PRODUCT',
        help_text="Type of item being sold"
    )
    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name='sale_items'
    )
    service = models.ForeignKey(
        'inventory.Service',
        on_delete=models.PROTECT,
        related_name='sale_items',
        null=True,
        blank=True
    )
    original_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Original product/service price before any override'
    )
    price_override_reason = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text='Reason for price override'
    )

    # Changed from PositiveIntegerField to IntegerField to allow negative values for refunds
    quantity = models.IntegerField()
    export_total_weight = models.DecimalField(
        decimal_places=4,
        max_digits=12,
        null=True,
        blank=True,
        help_text='Net weight in KGM — mandatory in T109 goodsDetails when invoiceIndustryCode=102',
    )
    export_piece_qty = models.DecimalField(
        decimal_places=2,
        max_digits=12,
        null=True,
        blank=True,
        help_text='Number of pieces — mandatory in T109 goodsDetails when invoiceIndustryCode=102',
    )
    export_piece_measure_unit = models.CharField(
        max_length=3,
        null=True,
        blank=True,
        help_text='3-char code from T115 exportRateUnit (e.g. "101"=per stick)',
    )
    # Removed MinValueValidator to allow negative values for refunds
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)

    tax_rate = models.CharField(max_length=1, choices=TAX_RATE_CHOICES, default='A')

    # Removed MinValueValidator to allow negative values for refunds
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    discount = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    description = models.TextField(blank=True, null=True)
    stock_deducted = models.BooleanField(default=False, verbose_name="Stock Deducted")

    class Meta:
        verbose_name = "Sale Item"
        verbose_name_plural = "Sale Items"
        ordering = ['id']
        constraints = [
            # Removed positive_quantity and non_negative_unit_price constraints
            # to allow negative values for refunds

            # Ensure either product OR service is set, but not both
            models.CheckConstraint(
                check=(
                        models.Q(product__isnull=False, service__isnull=True) |
                        models.Q(product__isnull=True, service__isnull=False)
                ),
                name='product_or_service_required'
            ),
        ]

    def __str__(self):
        """String representation that works for both products and services"""
        if self.product_id:
            try:
                item_name = self.product.name
            except:
                item_name = f"Product #{self.product_id}"
        elif self.service_id:
            try:
                item_name = self.service.name
            except:
                item_name = f"Service #{self.service_id}"
        else:
            item_name = 'Unknown'

        doc_num = self.sale.document_number if self.sale else 'N/A'
        qty_display = abs(self.quantity) if self.quantity < 0 else self.quantity
        prefix = "REFUND: " if self.quantity < 0 else ""
        return f"{prefix}{item_name} x {qty_display} - {doc_num}"

    def clean(self):
        """Enhanced model-level validation"""
        super().clean()

        # Validate that exactly one of product or service is set
        if not self.product_id and not self.service_id:
            raise ValidationError("Either product or service must be specified")

        if self.product_id and self.service_id:
            raise ValidationError("Cannot have both product and service in the same item")

        # Validate quantity based on transaction type
        if self.sale:
            if self.sale.transaction_type == 'SALE' and self.quantity <= 0:
                raise ValidationError({
                    'quantity': 'Quantity must be greater than 0 for sales'
                })
            elif self.sale.transaction_type == 'REFUND' and self.quantity >= 0:
                raise ValidationError({
                    'quantity': 'Quantity must be negative for refunds'
                })

        # Validate discount percentage
        if self.discount < 0 or self.discount > 100:
            raise ValidationError("Discount must be between 0 and 100 percent")

        # Set item_type based on what's provided
        if self.product_id:
            self.item_type = 'PRODUCT'
        elif self.service_id:
            self.item_type = 'SERVICE'
        else:
            raise ValidationError("Item type cannot be determined - no product or service")

    def get_export_details_for_efris(self):
        """Get export-specific fields for T109 goodsDetails"""
        if not self.sale.is_export_sale or self.item_type != 'PRODUCT':
            return {}

        return {
            "hsCode": self.product.hs_code or "",
            "hsName": self.product.hs_name or "",
            "totalWeight": f"{self.export_total_weight:.2f}" if self.export_total_weight else "0.00",
            "pieceQty": f"{self.export_piece_qty:.2f}" if self.export_piece_qty else "0.00",
            "pieceMeasureUnit": self.export_piece_measure_unit or "",
        }

    def save(self, *args, **kwargs):
        # Track original price before override
        if not self.pk:  # Only on creation
            if self.product:
                self.original_price = self.product.selling_price
            elif self.service:
                self.original_price = self.service.unit_price

        # Calculate totals with proper rounding (preserving sign for refunds)
        self.total_price = (self.unit_price * self.quantity).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        # Calculate discount amount (always work with absolute values)
        base_amount = abs(self.total_price)
        self.discount_amount = (
            (self.discount / Decimal('100')) * base_amount if self.discount else Decimal('0')
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Calculate final price after discount
        final_price = base_amount - self.discount_amount

        # Calculate tax (extracted from selling price)
        if self.tax_rate in ['A', 'D']:
            tax_calc = (final_price / Decimal('1.18') * Decimal('0.18')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        elif self.tax_rate == 'E':
            if self.product_id and self.product and getattr(self.product, 'excise_duty_rate', None):
                excise_rate = self.product.excise_duty_rate / Decimal('100')
                tax_calc = (final_price / (Decimal('1') + excise_rate) * excise_rate).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
            else:
                tax_calc = Decimal('0.00')
        else:
            tax_calc = Decimal('0.00')

        # Apply sign based on quantity for refunds (negative quantity = negative tax)
        self.tax_amount = tax_calc if self.quantity > 0 else -tax_calc

        # Run model validation
        self.full_clean()

        # Only deduct stock for new PRODUCT items in completed sales with positive quantities
        is_new = not self.pk
        should_deduct_stock = (
                is_new and
                self.sale.status in ['COMPLETED', 'PAID'] and
                self.sale.transaction_type == 'SALE' and
                self.item_type == 'PRODUCT' and
                self.product_id is not None and
                self.sale.document_type in ['RECEIPT', 'INVOICE'] and  # ✅ FIXED
                not self.stock_deducted and
                self.quantity > 0
        )

        skip_deduction = getattr(self, '_skip_deduction', False)
        if should_deduct_stock and not skip_deduction:
            self.deduct_stock()

        super().save(*args, **kwargs)

        # Update sale totals after saving item
        if not getattr(self, '_skip_sale_update', False):
            self.sale.update_totals()

    @property
    def item_name(self):
        """Get the name of the item (product or service)"""
        if self.product_id:
            try:
                return self.product.name
            except:
                return f"Product #{self.product_id}"
        elif self.service_id:
            try:
                return self.service.name
            except:
                return f"Service #{self.service_id}"
        return "Unknown Item"

    @property
    def item_code(self):
        """Get the code/SKU of the item"""
        if self.product_id:
            try:
                return self.product.sku or ''
            except:
                return ''
        elif self.service_id:
            try:
                return self.service.code or ''
            except:
                return ''
        return ''

    @property
    def line_total(self):
        """Compute total line amount (handles both sales and refunds)"""
        total = self.total_price or Decimal("0.00")
        discount = self.discount_amount or Decimal("0.00")

        # For refunds (negative quantity), total is already negative
        # Discount reduces the absolute value
        if self.quantity < 0:
            # For negative totals: -100 + (-10) = -110 (more negative)
            # But we want: -100 - (-10) = -90 (less negative refund)
            return total + discount
        else:
            # For positive totals: 100 - 10 = 90
            return total - discount

    @property
    def net_amount(self):
        """Return total price minus discount and tax"""
        total = self.total_price or Decimal("0.00")
        discount = self.discount_amount or Decimal("0.00")
        tax = self.tax_amount or Decimal("0.00")

        if self.quantity < 0:
            # For refunds
            return total + discount - tax
        else:
            # For sales
            return total - discount - tax

    @property
    def unit_of_measure(self):
        """Get unit of measure from product or service"""
        if self.product:
            return getattr(self.product, 'unit_of_measure', 'pcs')
        elif self.service:
            return getattr(self.service, 'unit_of_measure', '207')  # Hours
        return 'unit'

    @transaction.atomic
    def deduct_stock(self):
        """
        Deduct stock for product items only.
        INCLUDES IDEMPOTENCY CHECK to prevent duplicate deductions.
        """
        # Check if already deducted
        if self.stock_deducted:
            logger.warning(f"⚠️ Stock already deducted for {self.product.name}. Skipping.")
            return

        if self.item_type != 'PRODUCT' or not self.product:
            logger.info(f"Skipping stock deduction for service item: {self.item_name}")
            return

        # Don't deduct stock for negative quantities (refunds)
        if self.quantity <= 0:
            logger.info(f"Skipping stock deduction for refund item: {self.item_name}")
            return

        try:
            logger.info(f"Deducting stock for product: {self.product.name}")

            # Import here to avoid circular imports
            from inventory.models import Stock, StockMovement

            store_stock = Stock.objects.select_for_update().filter(
                product=self.product,
                store=self.sale.store
            ).first()

            if not store_stock:
                raise ValidationError(
                    f"No stock available for product {self.product.name} in store {self.sale.store.name}"
                )

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

            if updated_rows == 0:
                raise ValidationError("Stock update failed")

            # Create stock movement record
            movement_reference = (
                    self.sale.efris_invoice_number or
                    self.sale.document_number or
                    f"SALE-{self.sale.id}"
            )

            StockMovement.objects.create(
                product=self.product,
                store=self.sale.store,
                movement_type='SALE',
                quantity=self.quantity,
                reference=movement_reference,
                unit_price=self.unit_price,
                total_value=self.total_price,
                created_by=self.sale.created_by,
                notes=f'Sale item: {self.product.name} - Qty: {self.quantity}',
            )

            # Mark as deducted but DON'T save yet (will be saved by main save method)
            self.stock_deducted = True

            logger.info(f"✅ Stock deducted successfully: {self.product.name} - Qty: {self.quantity}")

        except Exception as e:
            logger.error(f"❌ Stock deduction error for {self.product.name}: {e}", exc_info=True)
            raise

    @transaction.atomic
    def restore_stock(self):
        """
        Restore stock for product items only when voiding/refunding.
        Services don't have stock to restore.
        Works with both positive quantities (void) and negative quantities (refund).
        """
        if self.item_type != 'PRODUCT' or not self.product:
            logger.info(f"Skipping stock restoration for service item: {self.item_name}")
            return  # Services don't have stock

        try:
            # Use absolute value of quantity for restoration
            restore_qty = abs(self.quantity)
            logger.info(f"Restoring stock for product: {self.product.name}, Qty: {restore_qty}")

            # Import here to avoid circular imports
            from inventory.models import Stock, StockMovement

            store_stock = Stock.objects.select_for_update().filter(
                product=self.product,
                store=self.sale.store
            ).first()

            if store_stock:
                Stock.objects.filter(id=store_stock.id).update(
                    quantity=F('quantity') + restore_qty,
                    last_updated=timezone.now()
                )
            else:
                # Create stock record if it doesn't exist
                Stock.objects.create(
                    product=self.product,
                    store=self.sale.store,
                    quantity=restore_qty,
                    last_updated=timezone.now()
                )

            movement_type = 'VOID' if self.sale.is_voided else 'REFUND'
            movement_reference = (
                    self.sale.efris_invoice_number or
                    self.sale.document_number or
                    f"RESTORE-{self.sale.id}"
            )

            StockMovement.objects.create(
                product=self.product,
                store=self.sale.store,
                movement_type=movement_type,
                quantity=restore_qty,
                reference=movement_reference,
                unit_price=self.unit_price,
                total_value=abs(self.total_price),
                created_by=self.sale.created_by,
                notes=f'Stock restoration: {movement_type.lower()} - {self.product.name}',
                efris_reference=self.sale.efris_invoice_number if self.sale.is_fiscalized else None
            )

            logger.info(f"✅ Stock restored successfully: {self.product.name} - Qty: {restore_qty}")

        except Exception as e:
            logger.error(f"❌ Stock restoration error for {self.product.name}: {e}", exc_info=True)
            raise ValidationError(f"Failed to restore stock: {str(e)}")


# ==================== ENHANCED: Receipt Model ====================
class Receipt(OfflineIDMixin, models.Model):
    """Receipt document for immediate payment sales"""
    sale = models.OneToOneField(
        Sale,
        on_delete=models.CASCADE,
        related_name='receipt_detail',
        verbose_name="Sale"
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True,
    )
    store = models.ForeignKey('stores.Store', on_delete=models.PROTECT, null=True, blank=True)
    receipt_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="Receipt Number"
    )
    printed_at = models.DateTimeField(auto_now_add=True, verbose_name="Printed At")
    printed_by = models.ForeignKey('accounts.CustomUser', on_delete=models.PROTECT, verbose_name="Printed By")

    # Enhanced receipt data
    receipt_data = models.JSONField(default=dict, verbose_name="Receipt Data")
    payment_summary = models.JSONField(default=dict, verbose_name="Payment Summary")
    customer_copy = models.BooleanField(default=True, verbose_name="Customer Copy")

    is_duplicate = models.BooleanField(default=False, verbose_name="Is Duplicate")
    print_count = models.PositiveIntegerField(default=1, verbose_name="Print Count")

    # Additional fields
    terminal_id = models.CharField(max_length=50, blank=True, null=True, verbose_name="Terminal ID")
    cashier_name = models.CharField(max_length=100, blank=True, null=True, verbose_name="Cashier Name")

    class Meta:
        verbose_name = "Receipt"
        verbose_name_plural = "Receipts"
        ordering = ['-printed_at']
        indexes = [
            models.Index(fields=['receipt_number']),
            models.Index(fields=['sale']),
            models.Index(fields=['printed_at']),
        ]

    def __str__(self):
        return f"Receipt #{self.receipt_number}"

    def save(self, *args, **kwargs):
        """
        Save receipt with proper number generation
        ✅ Handles cases where document_number already has prefix
        ✅ Defensive cleanup of double prefixes
        """
        import logging
        logger = logging.getLogger(__name__)

        # Auto-generate receipt number
        if not self.receipt_number and self.sale:
            # ✅ FIX: Check if document_number already has RCP- prefix
            if self.sale.document_number.startswith('RCP-'):
                # Use document_number as-is (already has prefix)
                self.receipt_number = self.sale.document_number
            else:
                # Add RCP- prefix
                self.receipt_number = f"RCP-{self.sale.document_number}"

        # ✅ DEFENSIVE: Clean up any double prefix that might exist
        # (in case old data has this issue)
        if self.receipt_number and self.receipt_number.startswith('RCP-RCP-'):
            self.receipt_number = self.receipt_number.replace('RCP-RCP-', 'RCP-', 1)
            logger.warning(f"🔧 Fixed duplicate RCP prefix: {self.receipt_number}")

        # Auto-populate store from sale
        if not self.store and self.sale:
            self.store = self.sale.store

        # Auto-populate payment summary
        if not self.payment_summary and self.sale:
            self.payment_summary = {
                'payment_method': self.sale.payment_method,
                'amount': str(self.sale.total_amount),
                'currency': self.sale.currency,
                'items_count': self.sale.item_count,
            }

        super().save(*args, **kwargs)

    @property
    def is_valid(self):
        """Check if receipt is valid (sale not voided/refunded)"""
        return not (self.sale.is_voided or self.sale.is_refunded)

    def increment_print_count(self):
        """Increment print count and mark as duplicate after first print"""
        if self.print_count == 1:
            self.is_duplicate = True
        self.print_count += 1
        self.save(update_fields=['print_count', 'is_duplicate'])


class Payment(OfflineIDMixin, models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='payments')
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True,
    )
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

    # ==================== NEW: Payment Type ====================
    PAYMENT_TYPE_CHOICES = [
        ('FULL', 'Full Payment'),
        ('PARTIAL', 'Partial Payment'),
        ('ADVANCE', 'Advance Payment'),
        ('FINAL', 'Final Payment'),
    ]

    payment_type = models.CharField(
        max_length=20,
        choices=PAYMENT_TYPE_CHOICES,
        default='FULL',
        verbose_name="Payment Type"
    )

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment of {self.amount} for {self.sale.document_number}"

    def clean(self):
        """Validate payment"""
        super().clean()

        # Validate payment doesn't exceed outstanding amount for invoices
        if self.sale.is_invoice and self.payment_type != 'ADVANCE':
            outstanding = self.sale.amount_outstanding
            if self.amount > outstanding:
                raise ValidationError(f"Payment amount {self.amount} exceeds outstanding amount {outstanding}")

    def save(self, *args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)

        # Auto-generate receipt number only when missing
        if not self.receipt_number and self.sale:
            if self.sale.document_number and self.sale.document_number.startswith('RCP-'):
                self.receipt_number = self.sale.document_number
            else:
                self.receipt_number = f"RCP-{self.sale.document_number}"

        # ✅ DEFENSIVE: Always clean double prefix, regardless of how receipt_number was set
        if self.receipt_number and self.receipt_number.startswith('RCP-RCP-'):
            self.receipt_number = self.receipt_number.replace('RCP-RCP-', 'RCP-', 1)
            logger.warning(f"🔧 Fixed duplicate RCP prefix: {self.receipt_number}")

        # Auto-populate store from sale
        if not self.store_id and self.sale:
            self.store = self.sale.store

        # Auto-populate payment summary
        if not self.payment_summary and self.sale:
            self.payment_summary = {
                'payment_method': self.sale.payment_method,
                'amount': str(self.sale.total_amount),
                'currency': self.sale.currency,
                'items_count': self.sale.item_count,
            }

        super().save(*args, **kwargs)

    def update_payment_status(self):
        """Update sale payment status based on payments"""
        if not self.sale.is_invoice:
            return

        total_paid = self.sale.amount_paid
        total_amount = self.sale.total_amount

        if total_paid >= total_amount:
            self.sale.payment_status = 'PAID'
            self.sale.status = 'COMPLETED'
        elif total_paid > 0:
            self.sale.payment_status = 'PARTIALLY_PAID'
        elif self.sale.days_overdue > 0:
            self.sale.payment_status = 'OVERDUE'
        else:
            self.sale.payment_status = 'PENDING'

        self.sale.save(update_fields=['payment_status', 'status'])

    def _update_sale_payment_status(self):
        """Helper method to update sale payment status without circular dependency"""
        from django.db.models import Sum
        from decimal import Decimal

        # Recalculate payment status without calling sale.save()
        sale = self.sale

        # Calculate total paid
        total_paid = sale.payments.filter(is_confirmed=True).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        total_amount = sale.total_amount or Decimal('0')

        # Determine new status
        new_payment_status = sale.payment_status
        new_status = sale.status

        if total_paid >= total_amount:
            new_payment_status = 'PAID'
            if sale.status in ['DRAFT', 'PENDING_PAYMENT']:
                new_status = 'COMPLETED'
        elif total_paid > 0:
            new_payment_status = 'PARTIALLY_PAID'
        else:
            new_payment_status = 'PENDING'

        # Check overdue
        if sale.document_type == 'INVOICE' and sale.due_date:
            today = timezone.now().date()
            if sale.due_date < today:
                if new_payment_status in ['PENDING', 'PARTIALLY_PAID']:
                    new_payment_status = 'OVERDUE'

        # Update sale directly using update() to avoid save() recursion
        if new_payment_status != sale.payment_status or new_status != sale.status:
            Sale.objects.filter(pk=sale.pk).update(
                payment_status=new_payment_status,
                status=new_status,
                updated_at=timezone.now()
            )

            # Refresh the sale instance
            self.sale.refresh_from_db()

            logger.info(f"Updated sale {sale.id} payment status to {new_payment_status}")


class Cart(OfflineIDMixin, models.Model):
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('CONFIRMED', 'Confirmed'),
        ('ABANDONED', 'Abandoned'),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True,blank=True
    )
    session_key = models.CharField(max_length=40, blank=True, null=True)
    user = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, null=True, blank=True)
    customer = models.ForeignKey('customers.Customer', on_delete=models.SET_NULL, null=True, blank=True)
    store = models.ForeignKey('stores.Store', on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)

    # ==================== NEW: Document type for cart ====================
    document_type = models.CharField(
        max_length=20,
        choices=Sale.DOCUMENT_TYPE_CHOICES,
        default='RECEIPT',
        verbose_name="Document Type"
    )

    # ==================== NEW: Additional fields for invoices ====================
    due_date = models.DateField(null=True, blank=True, verbose_name="Due Date")
    terms = models.TextField(blank=True, null=True, verbose_name="Terms")
    purchase_order = models.CharField(max_length=100, blank=True, null=True, verbose_name="Purchase Order")

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Shopping Cart"
        verbose_name_plural = "Shopping Carts"
        ordering = ['-created_at']

    def __str__(self):
        doc_type = self.get_document_type_display()
        return f"Cart #{self.id} - {doc_type} - {self.get_status_display()}"

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

        # Since tax is already in subtotal, we just subtract discount
        self.total_amount = (self.subtotal - self.discount_amount).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        self.save(update_fields=['subtotal', 'tax_amount', 'discount_amount', 'total_amount'])

    @transaction.atomic
    def confirm(self, payment_method, created_by, **kwargs):
        """Enhanced cart confirmation with document type support"""
        if self.status != 'OPEN':
            raise ValidationError("Cart is not open for confirmation")

        from stores.utils import validate_store_access
        try:
            validate_store_access(created_by, self.store, action='view', raise_exception=True)
        except PermissionDenied as e:
            raise ValidationError(f"User does not have access to store {self.store.name}")

        # Don't validate stock for proforma/estimate
        if self.document_type in ['RECEIPT', 'INVOICE']:
            for item in self.items.select_related('product').select_for_update():
                if item.product:  # Only check products, not services
                    store_stock = Stock.objects.select_for_update().filter(
                        product=item.product,
                        store=self.store
                    ).first()

                    if not store_stock or store_stock.quantity < item.quantity:
                        raise ValidationError(
                            f"Insufficient stock for {item.product.name} in store {self.store.name}. "
                            f"Available: {store_stock.quantity if store_stock else 0}, Required: {item.quantity}"
                        )

        # Create sale with document type
        sale = Sale.objects.create(
            store=self.store,
            created_by=created_by,
            customer=self.customer,
            document_type=self.document_type,
            payment_method=payment_method,
            due_date=self.due_date,
            subtotal=self.subtotal,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            total_amount=self.total_amount,
            notes=self.notes or '',
            currency='UGX',
            transaction_type='SALE',
        )

        # The Sale.save() method will automatically create Invoice/Receipt records
        # based on document_type, so we don't need to create them here

        # Move cart items to SaleItems
        for item in self.items.all():
            SaleItem.objects.create(
                sale=sale,
                product=item.product,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_price=item.total_price,
                tax_rate=item.tax_rate,
                tax_amount=item.tax_amount,
                discount=item.discount,
                discount_amount=item.discount_amount,
                description=item.description or (item.product.name if item.product else ''),
            )

        # Update sale totals
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
                            'status': self.status,
                            'document_type': self.document_type,
                        }
                    }
                )
        except Exception as e:
            logger.error(f"WebSocket Error for Cart {self.id}: {e}")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            self.send_cart_update()
        except Exception:
            pass  # Don't let WebSocket errors break cart operations


class CartItem(OfflineIDMixin, models.Model):
    TAX_RATE_CHOICES = SaleItem.TAX_RATE_CHOICES
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True,blank=True
    )
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