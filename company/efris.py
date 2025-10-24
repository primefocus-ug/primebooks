from typing import Dict, Any, Tuple, List
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class EFRISCompanyMixin:
    """Company-specific EFRIS methods that use business data directly"""

    def can_use_efris(self) -> Tuple[bool, str]:
        """Check if company can use EFRIS with detailed validation"""
        if not self.efris_enabled:
            return False, "EFRIS is not enabled for this company"

        if not self.has_active_access:
            return False, "Company access is suspended or expired"

        # Check required business fields
        validation_errors = self.get_efris_configuration_errors()
        if validation_errors:
            return False, f"Configuration errors: {'; '.join(validation_errors[:3])}"

        return True, "Company can use EFRIS"

    def get_efris_seller_details(self) -> Dict[str, Any]:
        """Get seller details for EFRIS using business data"""
        return {
            "tin": self.tin or "",
            "ninBrn": getattr(self, 'brn', '') or getattr(self, 'nin', '') or "",
            "legalName": self.name or "",
            "businessName": self.trading_name or self.name or "",
            "address": self.physical_address or "",
            "mobilePhone": self.phone or "",
            "emailAddress": self.email or "",
            "placeOfBusiness": self.physical_address or "",
            "referenceNo": ""
        }

    def validate_efris_configuration(self) -> Tuple[bool, List[str]]:
        """Validate company EFRIS configuration using business fields"""
        errors = []

        # Check business data completeness
        required_business_fields = {
            'tin': 'TIN Number',
            'name': 'Legal Company Name',
            'email': 'Primary Email',
            'phone': 'Primary Phone',
            'physical_address': 'Physical Address'
        }

        for field, display_name in required_business_fields.items():
            if not getattr(self, field, None):
                errors.append(f"Missing {display_name}")

        # Business name (can be trading_name or name)
        if not (self.trading_name or self.name):
            errors.append("Business name or legal name is required")

        # TIN format validation
        if self.tin and len(self.tin.replace(' ', '').replace('-', '')) != 10:
            errors.append("TIN must be exactly 10 digits")

        return len(errors) == 0, errors

    def get_efris_configuration_status(self) -> Dict[str, Any]:
        """Get comprehensive EFRIS configuration status"""
        is_valid, errors = self.validate_efris_configuration()

        return {
            'enabled': self.efris_enabled,
            'active': self.efris_is_active,
            'registered': self.efris_is_registered,
            'configuration_complete': is_valid,
            'errors': errors,
            'last_sync': self.efris_last_sync,
            'status_display': self.efris_status_display,
            'can_use': self.can_use_efris()[0],
            'api_url': self.efris_api_url,
            'mode': 'Production' if self.efris_is_production else 'Test'
        }