from django.utils import timezone
from typing import Tuple, List, Dict, Any


class EFRISProductMixin:
    """Product-specific EFRIS methods"""

    def get_efris_goods_data(self) -> Dict[str, Any]:
        """Get goods data for EFRIS"""
        return {
            "goodsName": self.efris_goods_name or self.name,
            "goodsCode": self.efris_goods_code or self.sku or f'PROD{self.pk:06d}',
            "measureUnit": self.efris_unit_of_measure_code or "U",
            "unitPrice": str(self.selling_price or 0),
            "currency": "101",  # UGX
            "commodityCategoryId": self.efris_commodity_category_id or "1010101000",
            "description": self.efris_goods_description or self.description or self.name,
        }

    def validate_for_efris_upload(self) -> Tuple[bool, List[str]]:
        """Validate product for EFRIS upload"""
        errors = []

        if not self.name or not self.name.strip():
            errors.append("Product name is required")

        if not self.sku or not self.sku.strip():
            errors.append("Product SKU is required")

        if not self.selling_price or self.selling_price <= 0:
            errors.append("Product must have a positive selling price")

        return len(errors) == 0, errors

    def mark_efris_uploaded(self, efris_response: Dict = None):
        """Mark product as uploaded to EFRIS"""
        self.efris_is_uploaded = True
        self.efris_upload_date = timezone.now()

        if efris_response and 'goodsId' in efris_response:
            self.efris_goods_id = efris_response['goodsId']

        self.save(update_fields=['efris_is_uploaded', 'efris_upload_date', 'efris_goods_id'])

