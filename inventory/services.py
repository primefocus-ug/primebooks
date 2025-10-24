from typing import List, Dict

from .models import Product
from efris.services import EFRISProductService


class InventoryEFRISService:
    def __init__(self, company):
        self.company = company
        self.efris_service = EFRISProductService(company)

    def upload_products(self, products: List[Product]):
        """Upload products to EFRIS"""
        return self.efris_service.upload_products(products)

    def bulk_prepare_products(self, products: List[Product]) -> List[Dict]:
        """Prepare multiple products for EFRIS upload"""
        valid_products = []

        for product in products:
            is_valid, errors = product.validate_for_efris_upload()
            if is_valid:
                valid_products.append(product.get_efris_goods_data())

        return valid_products