from typing import Dict, Any, Tuple
from django.utils import timezone

class EFRISInvoiceMixin:
    """Invoice-specific EFRIS methods"""

    def can_fiscalize(self, user=None) -> Tuple[bool, str]:
        """Check if invoice can be fiscalized"""
        if self.is_fiscalized:
            return False, "Invoice is already fiscalized"

        if not self.issue_date:
            return False, "Invoice issue date is required"

        if self.total_amount <= 0:
            return False, "Invoice must have positive total amount"

        # Check age
        days_old = (timezone.now().date() - self.issue_date.date()).days
        if days_old > 30:
            return False, f"Invoice is too old ({days_old} days)"

        return True, "Invoice can be fiscalized"

    def get_efris_basic_info(self) -> Dict[str, Any]:
        """Get basic information for EFRIS"""
        return {
            "invoiceNo": "",  # Will be assigned by EFRIS
            "issuedDate": self.issue_date.strftime('%Y-%m-%d %H:%M:%S'),
            "operator": getattr(self, 'operator_name', 'System'),
            "currency": getattr(self, 'currency_code', 'UGX'),
            "invoiceType": "1",  # Standard invoice
            "invoiceKind": "1",  # Invoice
        }

    def get_efris_summary(self) -> Dict[str, Any]:
        """Get summary for EFRIS"""
        net_amount = self.subtotal - (self.discount_amount or 0)

        return {
            "netAmount": str(net_amount),
            "taxAmount": str(self.tax_amount),
            "grossAmount": str(self.total_amount),
            "itemCount": str(self.get_item_count()),
            "modeCode": "1",  # Online mode
            "remarks": self.notes or "Invoice generated via EFRIS integration"
        }

    def get_item_count(self) -> int:
        """Get number of items in invoice"""
        if hasattr(self, 'items') and self.items.exists():
            return self.items.count()
        return 1

    def update_from_efris_response(self, efris_data: Dict):
        """Update invoice with EFRIS response data"""
        basic_info = efris_data.get('basicInformation', {})
        summary = efris_data.get('summary', {})

        if 'invoiceNo' in basic_info:
            self.fiscal_document_number = basic_info['invoiceNo']

        if 'antifakeCode' in basic_info:
            self.verification_code = basic_info['antifakeCode']

        if 'qrCode' in summary:
            self.qr_code = summary['qrCode']

        self.is_fiscalized = True
        self.fiscalization_time = timezone.now()
        self.save()

