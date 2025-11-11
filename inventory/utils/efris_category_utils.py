# inventory/utils/efris_category_utils.py

from company.models import EFRISCommodityCategory
from django.db.models import Q


class EFRISCategoryHelper:
    """
    Helper class for working with EFRIS Commodity Categories.
    Handles filtering for leaf nodes, products, and services.
    """

    @staticmethod
    def get_leaf_nodes_only(queryset=None):
        """
        Get only leaf node categories (is_leaf_node='101').
        These are the only categories that can be used for products/services.
        """
        if queryset is None:
            queryset = EFRISCommodityCategory.objects.all()
        return queryset.filter(is_leaf_node='101')

    @staticmethod
    def get_product_categories():
        """
        Get EFRIS categories for products only (serviceMark='101' or not '102').
        Returns only leaf nodes.
        """
        return EFRISCommodityCategory.objects.filter(
            is_leaf_node='101',
            service_mark='101'  # Product categories
        )

    @staticmethod
    def get_service_categories():
        """
        Get EFRIS categories for services only (serviceMark='102').
        Returns only leaf nodes.
        """
        return EFRISCommodityCategory.objects.filter(
            is_leaf_node='101',
            service_mark='102'  # Service categories
        )

    @staticmethod
    def validate_category_for_type(commodity_code, expected_type):
        """
        Validate that a commodity category code matches the expected type.

        Args:
            commodity_code: The EFRIS commodity category code
            expected_type: Either 'product' or 'service'

        Returns:
            dict with 'valid' (bool), 'message' (str), 'category' (object or None)
        """
        try:
            category = EFRISCommodityCategory.objects.get(
                commodity_category_code=commodity_code
            )

            # Check if it's a leaf node
            if category.is_leaf_node != '101':
                return {
                    'valid': False,
                    'message': 'Selected category is not a leaf node. Only leaf nodes can be used.',
                    'category': category
                }

            # Check if type matches
            actual_type = 'service' if category.service_mark == '102' else 'product'
            if actual_type != expected_type:
                return {
                    'valid': False,
                    'message': f'Category is a {actual_type}, but expected a {expected_type}.',
                    'category': category
                }

            return {
                'valid': True,
                'message': 'Category is valid',
                'category': category
            }

        except EFRISCommodityCategory.DoesNotExist:
            return {
                'valid': False,
                'message': 'Commodity category code not found in system',
                'category': None
            }

    @staticmethod
    def get_category_hierarchy(commodity_code):
        """
        Get the full hierarchy path for a commodity category.
        Useful for displaying breadcrumbs.

        Returns: List of category objects from root to leaf
        """
        try:
            category = EFRISCommodityCategory.objects.get(
                commodity_category_code=commodity_code
            )

            hierarchy = [category]
            current = category

            # Walk up the tree until we reach root (parentCode='0')
            while current.parent_code and current.parent_code != '0':
                try:
                    parent = EFRISCommodityCategory.objects.get(
                        commodity_category_code=current.parent_code
                    )
                    hierarchy.insert(0, parent)
                    current = parent
                except EFRISCommodityCategory.DoesNotExist:
                    break

            return hierarchy

        except EFRISCommodityCategory.DoesNotExist:
            return []

    @staticmethod
    def get_category_tree_for_display(category_type='product'):
        """
        Get hierarchical tree structure for display in forms/templates.
        Only includes leaf nodes.

        Args:
            category_type: 'product' or 'service'

        Returns: Dict with hierarchical structure
        """
        if category_type == 'product':
            leaf_categories = EFRISCategoryHelper.get_product_categories()
        else:
            leaf_categories = EFRISCategoryHelper.get_service_categories()

        # Build tree structure
        tree = {}
        for category in leaf_categories:
            hierarchy = EFRISCategoryHelper.get_category_hierarchy(
                category.commodity_category_code
            )

            # Build nested structure
            current_level = tree
            for level_cat in hierarchy:
                key = f"{level_cat.commodity_category_code} - {level_cat.commodity_category_name}"
                if key not in current_level:
                    current_level[key] = {
                        'category': level_cat,
                        'children': {}
                    }
                current_level = current_level[key]['children']

        return tree

    @staticmethod
    def search_categories(query, category_type=None, leaf_only=True):
        """
        Search EFRIS categories by name or code.

        Args:
            query: Search term
            category_type: 'product', 'service', or None for both
            leaf_only: If True, only return leaf nodes

        Returns: QuerySet of matching categories
        """
        queryset = EFRISCommodityCategory.objects.filter(
            Q(commodity_category_name__icontains=query) |
            Q(commodity_category_code__icontains=query)
        )

        if leaf_only:
            queryset = queryset.filter(is_leaf_node='101')

        if category_type == 'product':
            queryset = queryset.filter(service_mark='101')
        elif category_type == 'service':
            queryset = queryset.filter(service_mark='102')

        return queryset.order_by('commodity_category_name')


# Example usage in views/forms:
"""
# In a form for selecting EFRIS categories for products:
from inventory.utils.efris_category_utils import EFRISCategoryHelper

class ProductForm(forms.ModelForm):
    efris_category = forms.ModelChoiceField(
        queryset=EFRISCategoryHelper.get_product_categories(),
        required=True,
        label="EFRIS Commodity Category"
    )

    def clean_efris_category(self):
        category = self.cleaned_data.get('efris_category')
        if category:
            validation = EFRISCategoryHelper.validate_category_for_type(
                category.commodity_category_code,
                'product'
            )
            if not validation['valid']:
                raise forms.ValidationError(validation['message'])
        return category


# In a view for searching categories:
def search_efris_categories(request):
    query = request.GET.get('q', '')
    category_type = request.GET.get('type', 'product')

    results = EFRISCategoryHelper.search_categories(
        query=query,
        category_type=category_type,
        leaf_only=True
    )

    return JsonResponse({
        'results': [
            {
                'code': cat.commodity_category_code,
                'name': cat.commodity_category_name,
                'rate': cat.rate,
                'is_exempt': cat.is_exempt == '101',
                'is_zero_rate': cat.is_zero_rate == '101'
            }
            for cat in results[:20]  # Limit to 20 results
        ]
    })
"""