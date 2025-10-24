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

    Query params:
    - q: search query (min 3 chars)
    - type: 'product' or 'service'
    - page: pagination page (default 1)
    - limit: results per page (default 20, max 100)
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
                    'more': False
                }
            })

        # Determine service_mark based on type
        service_mark = '102' if category_type == 'service' else '101'

        # Build query - only leaf nodes
        queryset = EFRISCommodityCategory.objects.filter(
            is_leaf_node='101',  # Only leaf nodes
            service_mark=service_mark,  # Match type
            enable_status_code='1',  # Only enabled
        )

        # Search in code and name
        queryset = queryset.filter(
            Q(commodity_category_code__icontains=query) |
            Q(commodity_category_name__icontains=query)
        )

        # Order by relevance (exact matches first, then by name)
        queryset = queryset.order_by('commodity_category_name')

        # Pagination
        start = (page - 1) * limit
        end = start + limit
        total_count = queryset.count()
        results = queryset[start:end]

        # Format results for Select2/autocomplete
        formatted_results = []
        for cat in results:
            formatted_results.append({
                'id': cat.commodity_category_code,
                'text': f"{cat.commodity_category_code} - {cat.commodity_category_name}",
                'data': {
                    'code': cat.commodity_category_code,
                    'name': cat.commodity_category_name,
                    'rate': str(cat.rate) if cat.rate else '0.00',
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
                    'rate': str(category.rate) if category.rate else '0.00',
                    'is_leaf_node': category.is_leaf_node == '101',
                    'service_mark': 'service' if category.service_mark == '102' else 'product',
                    'is_zero_rate': category.is_zero_rate == '101',
                    'is_exempt': category.is_exempt == '101',
                    'excisable': getattr(category, 'excisable', '102') == '101',
                    'parent_code': category.parent_code or None,
                    'enable_status': category.enable_status_code == '1',
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
    """

    def get(self, request):
        total_categories = EFRISCommodityCategory.objects.count()

        leaf_nodes = EFRISCommodityCategory.objects.filter(
            is_leaf_node='101'
        ).count()

        products = EFRISCommodityCategory.objects.filter(
            service_mark='101',
            is_leaf_node='101'
        ).count()

        services = EFRISCommodityCategory.objects.filter(
            service_mark='102',
            is_leaf_node='101'
        ).count()

        exempt_categories = EFRISCommodityCategory.objects.filter(
            is_exempt='101',
            is_leaf_node='101'
        ).count()

        zero_rate_categories = EFRISCommodityCategory.objects.filter(
            is_zero_rate='101',
            is_leaf_node='101'
        ).count()

        return JsonResponse({
            'total_categories': total_categories,
            'leaf_nodes': leaf_nodes,
            'usable_products': products,
            'usable_services': services,
            'exempt_categories': exempt_categories,
            'zero_rate_categories': zero_rate_categories,
        })