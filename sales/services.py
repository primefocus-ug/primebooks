from typing import Tuple, Any
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


class SalesEFRISService:
    """App-specific EFRIS service for sales"""

    def __init__(self, company):
        self.company = company

    def prepare_sale_for_fiscalization(self, sale) -> Tuple[bool, str]:
        """Prepare sale for EFRIS fiscalization"""
        try:
            # Check if sale has required EFRIS methods
            if not hasattr(sale, 'can_fiscalize'):
                return False, "Sale model does not support EFRIS fiscalization"

            # Use sale's EFRIS mixin to validate
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

            return True, "Sale is ready for fiscalization"

        except Exception as e:
            logger.error(f"Error preparing sale {sale.id} for fiscalization: {e}")
            return False, f"Preparation error: {str(e)}"

    def create_invoice_for_fiscalization(self, sale, user) -> Tuple[bool, str, Any]:
        """Create invoice from sale for EFRIS fiscalization"""
        try:
            # Check if invoice already exists
            if hasattr(sale, 'invoice') and sale.invoice:
                return True, "Invoice already exists", sale.invoice

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

            # Create invoice with EFRIS-ready data
            invoice = Invoice.objects.create(
                sale=sale,
                store=sale.store,
                issue_date=timezone.now().date(),
                due_date=timezone.now().date() + timezone.timedelta(days=30),
                subtotal=sale.subtotal,
                tax_amount=sale.tax_amount,
                discount_amount=sale.discount_amount,
                total_amount=sale.total_amount,
                currency_code=sale.currency or 'UGX',
                business_type=business_type,
                operator_name=user.get_full_name() or str(user),
                created_by=user,
                status='SENT'
            )

            return True, f"Invoice {invoice.invoice_number} created successfully", invoice

        except Exception as e:
            logger.error(f"Error creating invoice for sale {sale.id}: {e}")
            return False, f"Invoice creation error: {str(e)}", None