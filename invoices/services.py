from typing import List, Tuple, Dict, Any
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


class InvoiceEFRISService:
    """App-specific EFRIS service for invoices"""

    def __init__(self, company):
        self.company = company
        # Import core EFRIS services
        try:
            from efris.services import EFRISInvoiceService
            self.core_service = EFRISInvoiceService(company)
        except ImportError:
            logger.error("Core EFRIS services not available")
            self.core_service = None

    def fiscalize_invoice(self, invoice, user=None) -> Tuple[bool, str]:
        """Fiscalize a single invoice using core EFRIS service"""
        if not self.core_service:
            return False, "EFRIS service not available"

        try:
            # Validate invoice can be fiscalized
            can_fiscalize, reason = invoice.can_fiscalize(user)
            if not can_fiscalize:
                return False, reason

            # Get EFRIS-formatted invoice data
            invoice_data = invoice.get_efris_invoice_data()

            # Use core service for fiscalization
            success, message = self.core_service.fiscalize_invoice(invoice, user)

            if success:
                # Log successful fiscalization
                logger.info(
                    f"Invoice {invoice.invoice_number} fiscalized successfully. "
                    f"FDN: {invoice.fiscal_document_number}"
                )

            return success, message

        except Exception as e:
            logger.error(f"Error fiscalizing invoice {invoice.id}: {e}")
            return False, f"Fiscalization error: {str(e)}"

    def bulk_fiscalize(self, invoices: List, user=None) -> Dict[str, Any]:
        """Bulk fiscalize multiple invoices"""
        if not self.core_service:
            return {
                'success': False,
                'message': 'EFRIS service not available',
                'successful_count': 0,
                'failed_count': len(invoices),
                'results': [],
                'errors': [{'invoice': 'All', 'error': 'EFRIS service not available'}]
            }

        results = {
            'success': False,
            'total_invoices': len(invoices),
            'successful_count': 0,
            'failed_count': 0,
            'results': [],
            'errors': []
        }

        for invoice in invoices:
            try:
                success, message = self.fiscalize_invoice(invoice, user)

                result = {
                    'invoice_id': invoice.id,
                    'invoice_number': invoice.invoice_number,
                    'success': success,
                    'message': message
                }

                if success:
                    results['successful_count'] += 1
                    result['fiscal_number'] = invoice.fiscal_document_number
                else:
                    results['failed_count'] += 1
                    results['errors'].append({
                        'invoice': invoice.invoice_number,
                        'error': message
                    })

                results['results'].append(result)

            except Exception as e:
                results['failed_count'] += 1
                results['errors'].append({
                    'invoice': invoice.invoice_number,
                    'error': str(e)
                })

        results['success'] = results['successful_count'] > 0
        results['message'] = (
            f"Processed {results['total_invoices']} invoices: "
            f"{results['successful_count']} successful, {results['failed_count']} failed"
        )

        return results

