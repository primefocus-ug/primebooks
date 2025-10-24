from django.db import models


class ProductCategoryManager(models.Manager):
    """Manager for product categories only"""

    def get_queryset(self):
        return super().get_queryset().filter(
            category_type='product',
            is_active=True
        )

    def with_efris_data(self):
        """Prefetch EFRIS commodity category data for efficiency"""
        return self.select_related('efris_commodity_category')

    def leaf_nodes_only(self):
        """Get only categories with leaf node EFRIS categories"""
        from company.models import EFRISCommodityCategory
        leaf_codes = EFRISCommodityCategory.objects.filter(
            is_leaf_node='101',
            service_mark='101'
        ).values_list('commodity_category_code', flat=True)

        return self.filter(efris_commodity_category_code__in=leaf_codes)


class ServiceCategoryManager(models.Manager):
    """Manager for service categories only"""

    def get_queryset(self):
        return super().get_queryset().filter(
            category_type='service',
            is_active=True
        )

    def leaf_nodes_only(self):
        """Get only categories with leaf node EFRIS categories"""
        from company.models import EFRISCommodityCategory
        leaf_codes = EFRISCommodityCategory.objects.filter(
            is_leaf_node='101',
            service_mark='102'  # Services only
        ).values_list('commodity_category_code', flat=True)

        return self.filter(efris_commodity_category_code__in=leaf_codes)


# Add to your Category model:
"""
from inventory.managers import ProductCategoryManager, ServiceCategoryManager

class Category(models.Model):
    # ... all your fields ...

    # Default manager (all categories)
    objects = models.Manager()

    # Custom managers
    products = ProductCategoryManager()
    services = ServiceCategoryManager()
"""