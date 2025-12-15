from typing import Tuple, Any
import logging
from django.utils import timezone
from decimal import Decimal

logger = logging.getLogger(__name__)


class SalesEFRISService:
    """App-specific EFRIS service for ALL sales"""

    def __init__(self, company):
        self.company = company

    def prepare_sale_for_fiscalization(self, sale) -> Tuple[bool, str]:
        """Prepare sale for EFRIS fiscalization - ALL completed sales"""
        try:
            # Check if sale has required EFRIS methods
            if not hasattr(sale, 'can_fiscalize'):
                return False, "Sale model does not support EFRIS fiscalization"

            # ALL completed sales can be fiscalized
            if sale.status not in ['COMPLETED', 'PAID']:
                return False, "Only completed or paid sales can be fiscalized"

            # Use sale's EFRIS mixin to validate (already updated to use store.can_fiscalize)
            can_fiscalize, reason = sale.can_fiscalize()
            if not can_fiscalize:
                return False, reason

            # Validate sale has all required data
            if not sale.items.exists():
                return False, "Sale must have items to fiscalize"

            # Check customer data if present
            if sale.customer:
                if hasattr(sale.customer, 'validate_for_efris'):
                    is_valid, errors = sale.customer.validate_for_efris()
                    if not is_valid:
                        logger.warning(f"Customer EFRIS validation issues: {errors}")
                        # Don't fail - just log warning

            # Validate financial amounts
            if not sale.total_amount or sale.total_amount <= Decimal('0'):
                return False, "Sale must have a positive total amount"

            return True, f"{sale.get_document_type_display()} is ready for fiscalization"

        except Exception as e:
            logger.error(f"Error preparing sale {sale.id} for fiscalization: {e}")
            return False, f"Preparation error: {str(e)}"

    def create_invoice_for_fiscalization(self, sale, user) -> Tuple[bool, str, Any]:
        """Create invoice from sale for EFRIS fiscalization"""
        try:
            # Check if invoice already exists
            if hasattr(sale, 'invoice_detail') and sale.invoice_detail:  # Changed from 'invoice' to 'invoice_detail'
                return True, "Invoice already exists", sale.invoice_detail

            # Import Invoice model
            from invoices.models import Invoice

            # Use Sale's EFRIS methods to determine business type
            business_type = 'B2C'  # Default
            if sale.customer and hasattr(sale.customer, 'get_efris_buyer_details'):
                buyer_details = sale.customer.get_efris_buyer_details()
                buyer_type = buyer_details.get('buyerType', '1')
                if buyer_type == '0':
                    business_type = 'B2B'
                elif buyer_type == '3':
                    business_type = 'B2G'

            # Create invoice with minimal fields - using sale relationship
            invoice = Invoice.objects.create(
                sale=sale,  # This is the OneToOne relationship
                store=sale.store,  # Store is still needed
                terms='',  # Required field
                purchase_order='',  # Required field (can be empty)

                # EFRIS-related fields
                efris_document_type='1',  # Normal Invoice
                business_type=business_type,

                # Operator and creator
                operator_name=user.get_full_name() or str(user),
                created_by=user,

                # Auto-fiscalize if store allows it
                auto_fiscalize=getattr(sale.store, 'auto_fiscalize_sales', True)
            )

            logger.info(f"✅ Created invoice {invoice.id} for sale {sale.id}")
            return True, f"Invoice {invoice.sale.document_number} created successfully", invoice

        except Exception as e:
            logger.error(f"❌ Error creating invoice for sale {sale.id}: {e}", exc_info=True)
            return False, f"Invoice creation error: {str(e)}", None

    def get_efris_data_from_sale(self, sale):
        """Extract EFRIS data from sale - works for ALL sales"""
        # Use sale's EFRIS mixin methods (already updated to use store config)
        data = {}

        # Basic information
        if hasattr(sale, 'get_efris_basic_info'):
            data['basicInformation'] = sale.get_efris_basic_info()

        # Summary
        if hasattr(sale, 'get_efris_summary'):
            data['summary'] = sale.get_efris_summary()

        # Goods details
        if hasattr(sale, 'get_efris_goods_details'):
            data['goodsDetails'] = sale.get_efris_goods_details()

        # Payment details
        if hasattr(sale, 'get_efris_payment_details'):
            data['payWay'] = sale.get_efris_payment_details()

        # Tax details
        if hasattr(sale, '_build_efris_tax_details'):
            data['taxDetails'] = sale._build_efris_tax_details()

        # Seller details - use store data with company fallback
        if sale.store:
            # Get store config (already includes company fallback)
            if hasattr(sale.store, 'effective_efris_config'):
                store_config = sale.store.effective_efris_config
            else:
                store_config = {}

            # Get TIN from store or config
            tin = sale.store.tin or store_config.get('tin', '')

            # Get NIN/BRN from store or config
            nin_brn = sale.store.nin or store_config.get('nin', '')

            # Get business details
            legal_name = store_config.get('legal_name', sale.store.company.name if sale.store.company else '')
            business_name = sale.store.name  # Use store name as business name
            address = sale.store.physical_address or store_config.get('business_address', '')
            phone = sale.store.phone or store_config.get('phone', '')
            email = sale.store.email or store_config.get('email', '')

            data['sellerDetails'] = {
                "tin": tin,
                "ninBrn": nin_brn,
                "legalName": legal_name,
                "businessName": business_name,
                "address": address,
                "mobilePhone": phone,
                "emailAddress": email,
            }
        else:
            # Fallback to company if no store (shouldn't happen)
            if sale.store and sale.store.company:
                company = sale.store.company
                data['sellerDetails'] = {
                    "tin": getattr(company, 'tin', ''),
                    "ninBrn": getattr(company, 'brn', '') or getattr(company, 'nin', ''),
                    "legalName": getattr(company, 'name', ''),
                    "businessName": getattr(company, 'trading_name', '') or getattr(company, 'name', ''),
                    "address": getattr(company, 'physical_address', ''),
                    "mobilePhone": getattr(company, 'phone', ''),
                    "emailAddress": getattr(company, 'email', ''),
                }

        # Buyer details from customer (unchanged)
        if sale.customer:
            # Determine buyer type
            buyer_type = "1"  # B2C default
            if hasattr(sale.customer, 'customer_type') and sale.customer.customer_type:
                if sale.customer.customer_type.upper() == 'BUSINESS':
                    buyer_type = "0"  # B2B
                elif sale.customer.customer_type.upper() in ['GOVERNMENT', 'PUBLIC']:
                    buyer_type = "3"  # B2G
            elif getattr(sale.customer, 'tin', None):
                buyer_type = "0"  # B2B if has TIN

            data['buyerDetails'] = {
                "buyerTin": getattr(sale.customer, 'tin', '') or '',
                "buyerNinBrn": getattr(sale.customer, 'nin', '') or getattr(sale.customer, 'brn', '') or '',
                "buyerLegalName": sale.customer.name or 'Walk-in Customer',
                "buyerEmail": getattr(sale.customer, 'email', '') or '',
                "buyerMobilePhone": getattr(sale.customer, 'phone', '') or '',
                "buyerAddress": getattr(sale.customer, 'physical_address', '') or '',
                "buyerType": buyer_type
            }
        else:
            data['buyerDetails'] = {
                "buyerType": "1",
                "buyerLegalName": "Walk-in Customer",
                "buyerAddress": "",
                "buyerEmail": "",
                "buyerMobilePhone": "",
                "buyerTin": "",
                "buyerNinBrn": ""
            }

        return data

    def get_efris_api_credentials(self, store):
        """Get EFRIS API credentials from store with fallback to company"""
        if not store:
            return {}

        # Get store config (already includes company fallback)
        if hasattr(store, 'effective_efris_config'):
            store_config = store.effective_efris_config
        else:
            store_config = {}

        return {
            'client_id': store_config.get('client_id', ''),
            'api_key': store_config.get('api_key', ''),
            'private_key': store_config.get('private_key', ''),
            'public_certificate': store_config.get('public_certificate', ''),
            'key_password': store_config.get('key_password', ''),
            'is_production': store_config.get('is_production', False),
            'device_number': store_config.get('device_number', ''),
        }



class SalesDocumentService:
    """Service for handling different document types"""

    @staticmethod
    def create_document(document_type, store, customer, items_data, user, **kwargs):
        """Create sale document based on type"""
        from .models import Sale, SaleItem

        # Calculate totals
        subtotal = Decimal('0')
        tax_amount = Decimal('0')

        for item_data in items_data:
            quantity = item_data['quantity']
            unit_price = item_data['unit_price']
            discount = item_data.get('discount', Decimal('0'))

            item_total = unit_price * quantity
            item_discount = (item_total * discount) / Decimal('100')
            item_subtotal = item_total - item_discount

            # Calculate tax (18% VAT)
            item_tax = (item_subtotal / Decimal('1.18') * Decimal('0.18')).quantize(Decimal('0.01'))

            subtotal += item_subtotal
            tax_amount += item_tax

        discount_amount = kwargs.get('discount_amount', Decimal('0'))
        total_amount = (subtotal - discount_amount).quantize(Decimal('0.01'))

        # Create sale
        sale = Sale.objects.create(
            document_type=document_type,
            store=store,
            customer=customer,
            created_by=user,
            payment_method=kwargs.get('payment_method', 'CASH'),
            currency=kwargs.get('currency', 'UGX'),
            subtotal=subtotal,
            tax_amount=tax_amount,
            discount_amount=discount_amount,
            total_amount=total_amount,
            due_date=kwargs.get('due_date'),
            notes=kwargs.get('notes', ''),
            status='COMPLETED' if document_type == 'RECEIPT' else 'PENDING_PAYMENT',
            payment_status='PAID' if document_type == 'RECEIPT' else 'PENDING'
        )

        # Create sale items
        for item_data in items_data:
            SaleItem.objects.create(sale=sale, **item_data, _skip_sale_update=True)

        # Update totals
        sale.update_totals()

        # Create document-specific records
        if document_type == 'RECEIPT':
            from .models import Receipt
            Receipt.objects.create(
                sale=sale,
                printed_by=user,
                receipt_number=f"RCP-{sale.document_number}",
                receipt_data={
                    'items': [item.item_name for item in sale.items.all()],
                    'totals': {
                        'subtotal': str(sale.subtotal),
                        'tax': str(sale.tax_amount),
                        'discount': str(sale.discount_amount),
                        'total': str(sale.total_amount),
                    }
                }
            )
        elif document_type == 'INVOICE':
            from invoices.models import Invoice
            Invoice.objects.create(
                sale=sale,
                terms=kwargs.get('terms', ''),
                purchase_order=kwargs.get('purchase_order', ''),
                due_date=sale.due_date,
                status='SENT',
                fiscalization_status='pending'
            )

        return sale

    @staticmethod
    def convert_to_invoice(sale, due_date=None, terms=None):
        """Convert proforma/estimate to invoice"""
        if sale.document_type not in ['PROFORMA', 'ESTIMATE']:
            raise ValueError(f"Cannot convert {sale.get_document_type_display()} to invoice")

        # Create new invoice sale
        invoice_sale = sale.convert_to_invoice(due_date=due_date, terms=terms)
        return invoice_sale

    @staticmethod
    def get_document_summary(store, start_date, end_date, document_type=None):
        """Get document summary by type"""
        from .models import Sale
        from django.db.models import Sum, Count

        queryset = Sale.objects.filter(
            store=store,
            created_at__date__range=[start_date, end_date]
        )

        if document_type:
            queryset = queryset.filter(document_type=document_type)

        summary = queryset.aggregate(
            total_count=Count('id'),
            total_amount=Sum('total_amount'),
            total_tax=Sum('tax_amount'),
            total_discount=Sum('discount_amount')
        )

        # Breakdown by document type
        type_breakdown = Sale.objects.filter(
            store=store,
            created_at__date__range=[start_date, end_date]
        ).values('document_type').annotate(
            count=Count('id'),
            amount=Sum('total_amount')
        ).order_by('document_type')

        return {
            'summary': summary,
            'type_breakdown': type_breakdown,
            'document_type': document_type or 'ALL'
        }