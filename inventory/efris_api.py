# inventory/views/efris_api.py
from django.http import JsonResponse
from django.views import View
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from company.models import EFRISCommodityCategory


@method_decorator(login_required, name='dispatch')
class EFRISCategoryAutocompleteView(View):
    """
    AJAX endpoint for autocomplete search of EFRIS commodity categories.
    Filters by type (product/service) and only returns leaf nodes.
    """

    def get(self, request):
        query = request.GET.get('q', '').strip()
        category_type = request.GET.get('type', 'product')  # 'product' or 'service'
        page = int(request.GET.get('page', 1))
        limit = min(int(request.GET.get('limit', 20)), 100)

        # Minimum 3 characters for search
        if len(query) < 3:
            return JsonResponse({
                'results': [],
                'pagination': {
                    'more': False,
                    'total': 0,
                    'page': page,
                }
            })

        # Determine service_mark based on type
        service_mark = '102' if category_type == 'service' else '101'

        # Build query - only leaf nodes that are enabled
        queryset = EFRISCommodityCategory.objects.filter(
            is_leaf_node='101',  # Only leaf nodes (can be used in categories)
            service_mark=service_mark,  # Match type (product or service)
            enable_status_code='1',  # Only enabled categories
        )

        # Search in code and name (case-insensitive)
        queryset = queryset.filter(
            Q(commodity_category_code__icontains=query) |
            Q(commodity_category_name__icontains=query)
        )

        # Order by relevance (exact code matches first, then by name)
        queryset = queryset.extra(
            select={
                'code_match': "CASE WHEN commodity_category_code LIKE %s THEN 0 ELSE 1 END"
            },
            select_params=[f"{query}%"]
        ).order_by('code_match', 'commodity_category_name')

        # Pagination
        start = (page - 1) * limit
        end = start + limit
        total_count = queryset.count()
        results = queryset[start:end]

        # Format results for Select2
        formatted_results = []
        for cat in results:
            formatted_results.append({
                'id': cat.commodity_category_code,
                'text': f"{cat.commodity_category_code} - {cat.commodity_category_name}",
                'data': {
                    'code': cat.commodity_category_code,
                    'name': cat.commodity_category_name,
                    'rate': str(cat.rate) if cat.rate else '18.00',
                    'is_exempt': cat.is_exempt == '101',
                    'is_zero_rate': cat.is_zero_rate == '101',
                    'excisable': getattr(cat, 'excisable', '102') == '101',
                    'level': cat.commodity_category_level,
                }
            })

        return JsonResponse({
            'results': formatted_results,
            'pagination': {
                'more': end < total_count,
                'total': total_count,
                'page': page,
            }
        })


@method_decorator(login_required, name='dispatch')
class EFRISCategoryDetailView(View):
    """
    Get detailed information about a specific EFRIS category.
    Used to populate form fields when a category is selected.
    """

    def get(self, request, code):
        try:
            category = EFRISCommodityCategory.objects.get(
                commodity_category_code=code
            )

            return JsonResponse({
                'success': True,
                'data': {
                    'code': category.commodity_category_code,
                    'name': category.commodity_category_name,
                    'level': category.commodity_category_level,
                    'rate': str(category.rate) if category.rate else '18.00',
                    'is_leaf_node': category.is_leaf_node == '101',
                    'service_mark': 'service' if category.service_mark == '102' else 'product',
                    'is_zero_rate': category.is_zero_rate == '101',
                    'is_exempt': category.is_exempt == '101',
                    'excisable': getattr(category, 'excisable', '102') == '101',
                    'parent_code': category.parent_code or None,
                    'enable_status': category.enable_status_code == '1',
                    'zero_rate_start_date': category.zero_rate_start_date or None,
                    'zero_rate_end_date': category.zero_rate_end_date or None,
                    'exempt_rate_start_date': category.exempt_rate_start_date or None,
                    'exempt_rate_end_date': category.exempt_rate_end_date or None,
                }
            })

        except EFRISCommodityCategory.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Category not found'
            }, status=404)


@method_decorator(login_required, name='dispatch')
class EFRISCategoryStatsView(View):
    """
    Get statistics about EFRIS categories for dashboard/info display.
    Useful for showing users how many categories are available.
    """

    def get(self, request):
        # Total categories in database
        total_categories = EFRISCommodityCategory.objects.count()

        # Total leaf nodes (usable categories)
        leaf_nodes = EFRISCommodityCategory.objects.filter(
            is_leaf_node='101'
        ).count()

        # Usable product categories (leaf nodes + enabled + products)
        products = EFRISCommodityCategory.objects.filter(
            service_mark='101',  # Products
            is_leaf_node='101',  # Leaf nodes only
            enable_status_code='1'  # Enabled
        ).count()

        # Usable service categories (leaf nodes + enabled + services)
        services = EFRISCommodityCategory.objects.filter(
            service_mark='102',  # Services
            is_leaf_node='101',  # Leaf nodes only
            enable_status_code='1'  # Enabled
        ).count()

        # Exempt categories (leaf nodes only)
        exempt_categories = EFRISCommodityCategory.objects.filter(
            is_exempt='101',
            is_leaf_node='101'
        ).count()

        # Zero rate categories (leaf nodes only)
        zero_rate_categories = EFRISCommodityCategory.objects.filter(
            is_zero_rate='101',
            is_leaf_node='101'
        ).count()

        # Excisable categories (if field exists)
        try:
            excisable_categories = EFRISCommodityCategory.objects.filter(
                excisable='101',
                is_leaf_node='101'
            ).count()
        except:
            excisable_categories = 0

        return JsonResponse({
            'total_categories': total_categories,
            'leaf_nodes': leaf_nodes,
            'usable_products': products,
            'usable_services': services,
            'exempt_categories': exempt_categories,
            'zero_rate_categories': zero_rate_categories,
            'excisable_categories': excisable_categories,
        })


@method_decorator(login_required, name='dispatch')
class CategoryDetailAPIView(View):
    """
    Get details of a user's category including EFRIS info.
    Used when selecting category in product form.
    """

    def get(self, request, pk):
        from inventory.models import Category

        try:
            category = Category.objects.get(pk=pk)

            efris_data = None
            if category.efris_commodity_category:
                efris_cat = category.efris_commodity_category
                efris_data = {
                    'code': efris_cat.commodity_category_code,
                    'name': efris_cat.commodity_category_name,
                    'rate': str(efris_cat.rate) if efris_cat.rate else '18.00',
                    'is_exempt': efris_cat.is_exempt == '101',
                    'is_zero_rate': efris_cat.is_zero_rate == '101',
                    'excisable': getattr(efris_cat, 'excisable', '102') == '101',
                }

            return JsonResponse({
                'success': True,
                'id': category.id,
                'name': category.name,
                'code': category.code,
                'category_type': category.category_type,
                'efris_commodity_category': efris_data,
                'efris_auto_sync': category.efris_auto_sync,
                'efris_is_uploaded': category.efris_is_uploaded,
            })

        except Category.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Category not found'
            }, status=404)