from typing import Dict,Tuple,List,Any


class EFRISCustomerMixin:
    """Customer-specific EFRIS methods"""

    def get_efris_buyer_details(self) -> Dict[str, Any]:
        """Get buyer details for EFRIS"""
        # Determine buyer type
        buyer_type = "1"  # B2C default
        if hasattr(self, 'customer_type'):
            if self.customer_type and self.customer_type.upper() == 'BUSINESS':
                buyer_type = "0"  # B2B
        elif self.tin:
            buyer_type = "0"  # B2B if has TIN

        return {
            "buyerTin": self.tin or "",
            "buyerNinBrn": self.nin or self.brn or "",
            "buyerLegalName": self.name or "Unknown Customer",
            "buyerType": buyer_type,
            "buyerEmail": self.email or "",
            "buyerMobilePhone": self.phone or "",
            "buyerAddress": self.physical_address or self.postal_address or ""
        }

    def validate_for_efris(self) -> Tuple[bool, List[str]]:
        """Validate customer data for EFRIS according to new requirements"""
        errors = []

        # Basic requirements for all customers
        if not self.name or not self.name.strip():
            errors.append("Customer name is required")

        if not self.phone or not self.phone.strip():
            errors.append("Customer phone number is required")

        # Business/Government requirements
        customer_type = getattr(self, 'customer_type', '').upper()
        if customer_type in ['BUSINESS', 'GOVERNMENT']:
            if not getattr(self, 'tin', None):
                errors.append("Business and Government customers must have TIN for eFRIS registration")

        return len(errors) == 0, errors

    def enrich_from_efris_data(self, efris_data: Dict) -> List[str]:
        """Update customer with EFRIS data"""
        updates = []

        if not self.business_name and efris_data.get('business_name'):
            self.business_name = efris_data['business_name']
            updates.append('business_name')

        if not self.email and efris_data.get('email'):
            self.email = efris_data['email']
            updates.append('email')

        # Add other fields as needed

        if updates:
            self.save(update_fields=updates)

        return updates

