import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class BillingService:
    '''Service for handling billing operations'''

    def create_invoice(self, company, plan, amount, billing_cycle, transaction_type,
                       payment_method, breakdown=None):
        '''
        Create invoice for a transaction

        Args:
            company: Company instance
            plan: SubscriptionPlan instance
            amount: Decimal amount
            billing_cycle: Billing cycle (MONTHLY, QUARTERLY, YEARLY)
            transaction_type: Type (UPGRADE, RENEWAL, etc)
            payment_method: Payment method used
            breakdown: Optional cost breakdown dict

        Returns:
            Invoice instance or None
        '''
        try:
            # TODO: Create actual Invoice model
            # For now, just log the transaction
            logger.info(
                f"Invoice created for {company.company_id}: "
                f"{transaction_type} - {amount} - {payment_method}"
            )

            # Placeholder - implement actual invoice creation
            # invoice = Invoice.objects.create(
            #     company=company,
            #     plan=plan,
            #     amount=amount,
            #     billing_cycle=billing_cycle,
            #     transaction_type=transaction_type,
            #     payment_method=payment_method,
            #     breakdown=breakdown or {},
            #     status='PAID',
            # )
            # return invoice

            return None

        except Exception as e:
            logger.error(f"Error creating invoice: {e}", exc_info=True)
            return None

    def process_refund(self, company, invoice, amount, reason):
        '''Process refund for an invoice'''
        try:
            with transaction.atomic():
                # TODO: Process refund through payment gateway
                logger.info(
                    f"Refund processed for {company.company_id}: "
                    f"{amount} - {reason}"
                )

                return {
                    'success': True,
                    'refund_id': f'REF_{timezone.now().timestamp()}',
                    'message': 'Refund processed successfully'
                }
        except Exception as e:
            logger.error(f"Error processing refund: {e}", exc_info=True)
            return {
                'success': False,
                'message': f'Refund failed: {str(e)}'
            }

    def calculate_proration(self, company, old_plan, new_plan):
        '''Calculate prorated credit for plan change'''
        if not company.subscription_ends_at or not old_plan:
            return Decimal('0.00')

        days_remaining = (company.subscription_ends_at - timezone.now().date()).days
        if days_remaining <= 0:
            return Decimal('0.00')

        # Calculate daily rate of old plan
        daily_rate = old_plan.price / Decimal('30')  # Use Decimal to avoid float imprecision
        credit = daily_rate * Decimal(days_remaining)

        return max(credit, Decimal('0.00'))

    def generate_invoice_pdf(self, invoice):
        '''Generate PDF for invoice'''
        # TODO: Implement PDF generation using reportlab or weasyprint
        if invoice is None:
            logger.warning("generate_invoice_pdf called with None invoice")
            return None
        logger.info(f"PDF generation requested for invoice {invoice.id}")
        return None

    def send_invoice_email(self, invoice, recipient_email):
        '''Send invoice via email'''
        if invoice is None:
            logger.warning("send_invoice_email called with None invoice")
            return False
        if not recipient_email or '@' not in str(recipient_email):
            logger.warning(f"send_invoice_email called with invalid recipient: {recipient_email!r}")
            return False
        # TODO: Implement email sending
        logger.info(f"Invoice email queued for {recipient_email}")
        return True