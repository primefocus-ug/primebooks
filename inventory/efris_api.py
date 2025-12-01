from django.http import JsonResponse
from django.views import View
from django.db.models import Q, Count, Exists, OuterRef
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.views.decorators.cache import cache_page
from company.models import EFRISCommodityCategory
import logging

logger = logging.getLogger(__name__)


@method_decorator(login_required, name='dispatch')
class EFRISCategoryAutocompleteView(View):
    """
    Fast autocomplete for Select2 integration.
    Optimized with minimal fields and smart caching.
    """

    def get(self, request):
        query = request.GET.get('q', '').strip()
        category_type = request.GET.get('type', 'product')
        page = int(request.GET.get('page', 1))
        limit = min(int(request.GET.get('limit', 20)), 50)  # Max 50 per page

        logger.info(f"EFRIS Autocomplete - Query: '{query}', Type: {category_type}, Page: {page}")

        # Minimum 2 characters for search (reduced from 3)
        if len(query) < 2:
            return JsonResponse({
                'results': [],
                'pagination': {
                    'more': False,
                    'total': 0,
                    'page': page,
                }
            })

        # Cache key for this specific search
        cache_key = f'efris_autocomplete_{category_type}_{query}_{page}_{limit}'
        cached_result = cache.get(cache_key)

        if cached_result:
            logger.info(f"Returning cached autocomplete results for: {query}")
            return JsonResponse(cached_result)

        service_mark = '101' if category_type == 'service' else '102'

        try:
            # Optimized query with only() for minimal fields
            queryset = EFRISCommodityCategory.objects.filter(
                is_leaf_node='101',
                service_mark=service_mark,
                enable_status_code='1',
            ).filter(
                Q(commodity_category_code__icontains=query) |
                Q(commodity_category_name__icontains=query)
            ).only(
                'commodity_category_code',
                'commodity_category_name',
                'rate',
                'is_exempt',
                'is_zero_rate',
                'commodity_category_level'
            )

            # Get count efficiently
            total_count = queryset.count()
            logger.info(f"Found {total_count} matching categories")

            # Simple ordering for speed
            queryset = queryset.order_by('commodity_category_name')

            # Paginate
            start = (page - 1) * limit
            end = start + limit
            results = list(queryset[start:end])

            # Format results for Select2
            formatted_results = [
                {
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
                }
                for cat in results
            ]

            response_data = {
                'results': formatted_results,
                'pagination': {
                    'more': end < total_count,
                    'total': total_count,
                    'page': page,
                }
            }

            # Cache for 10 minutes
            cache.set(cache_key, response_data, 60 * 10)

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Autocomplete error: {str(e)}")
            return JsonResponse({
                'results': [],
                'pagination': {'more': False, 'total': 0, 'page': page}
            })


@method_decorator(login_required, name='dispatch')
class EFRISCategoryDetailView(View):
    """
    Get detailed information about a specific EFRIS category.
    Heavily cached since category details don't change.
    """

    def get(self, request, code):
        # Cache category details for 1 hour
        cache_key = f'efris_category_detail_{code}'
        cached_data = cache.get(cache_key)

        if cached_data:
            return JsonResponse(cached_data)

        try:
            category = EFRISCommodityCategory.objects.only(
                'commodity_category_code',
                'commodity_category_name',
                'commodity_category_level',
                'rate',
                'is_leaf_node',
                'service_mark',
                'is_zero_rate',
                'is_exempt',
                'parent_code',
                'enable_status_code',
                'zero_rate_start_date',
                'zero_rate_end_date',
                'exempt_rate_start_date',
                'exempt_rate_end_date'
            ).get(commodity_category_code=code)

            response_data = {
                'success': True,
                'data': {
                    'code': category.commodity_category_code,
                    'name': category.commodity_category_name,
                    'level': category.commodity_category_level,
                    'rate': str(category.rate) if category.rate else '18.00',
                    'is_leaf_node': category.is_leaf_node == '101',
                    'service_mark': 'service' if category.service_mark == '101' else 'product',
                    'is_zero_rate': category.is_zero_rate == '101',
                    'is_exempt': category.is_exempt == '101',
                    'excisable': getattr(category, 'excisable', '102') == '101',
                    'parent_code': category.parent_code or None,
                    'enable_status': category.enable_status_code == '1',
                    'zero_rate_start_date': str(
                        category.zero_rate_start_date) if category.zero_rate_start_date else None,
                    'zero_rate_end_date': str(category.zero_rate_end_date) if category.zero_rate_end_date else None,
                    'exempt_rate_start_date': str(
                        category.exempt_rate_start_date) if category.exempt_rate_start_date else None,
                    'exempt_rate_end_date': str(
                        category.exempt_rate_end_date) if category.exempt_rate_end_date else None,
                }
            }

            # Cache for 1 hour
            cache.set(cache_key, response_data, 60 * 60)

            return JsonResponse(response_data)

        except EFRISCommodityCategory.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Category not found'
            }, status=404)
        except Exception as e:
            logger.error(f"Error fetching category detail: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'Failed to load category details'
            }, status=500)


@method_decorator(login_required, name='dispatch')
class EFRISCategoryStatsView(View):
    """
    Get statistics about EFRIS categories.
    Heavily cached since stats don't change often.
    """

    def get(self, request):
        cache_key = 'efris_category_stats_v2'
        cached_stats = cache.get(cache_key)

        if cached_stats:
            logger.info("Returning cached EFRIS stats")
            return JsonResponse(cached_stats)

        try:
            logger.info("Calculating fresh EFRIS stats")

            # Use aggregate queries for better performance
            from django.db.models import Q, Count

            stats = EFRISCommodityCategory.objects.aggregate(
                total=Count('id'),
                leaf_nodes=Count('id', filter=Q(is_leaf_node='101')),
                products=Count('id', filter=Q(
                    service_mark='101',
                    is_leaf_node='101',
                    enable_status_code='1'
                )),
                services=Count('id', filter=Q(
                    service_mark='102',
                    is_leaf_node='101',
                    enable_status_code='1'
                )),
                exempt=Count('id', filter=Q(
                    is_exempt='101',
                    is_leaf_node='101'
                )),
                zero_rate=Count('id', filter=Q(
                    is_zero_rate='101',
                    is_leaf_node='101'
                ))
            )

            response_data = {
                'total_categories': stats['total'],
                'leaf_nodes': stats['leaf_nodes'],
                'usable_products': stats['products'],
                'usable_services': stats['services'],
                'exempt_categories': stats['exempt'],
                'zero_rate_categories': stats['zero_rate'],
                'excisable_categories': 0,  # Calculate separately if needed
            }

            # Cache for 1 hour
            cache.set(cache_key, response_data, 60 * 60)

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Error calculating stats: {str(e)}")
            return JsonResponse({
                'total_categories': 0,
                'leaf_nodes': 0,
                'usable_products': 0,
                'usable_services': 0,
                'exempt_categories': 0,
                'zero_rate_categories': 0,
                'excisable_categories': 0,
            })


@method_decorator(login_required, name='dispatch')
class EFRISCategoryTreeView(View):
    """
    Get root level categories only for tree view.
    Children are loaded on-demand via EFRISCategoryChildrenView.
    """

    def get(self, request):
        category_type = request.GET.get('type', 'product')
        service_mark = '101' if category_type == 'service' else '102'

        logger.info(f"Loading EFRIS category tree roots for type: {category_type}")

        # Cache key for this tree
        cache_key = f'efris_tree_root_{category_type}'
        cached_tree = cache.get(cache_key)

        if cached_tree:
            logger.info("Returning cached tree roots")
            return JsonResponse(cached_tree)

        try:
            # Get ONLY root level categories (level 1 or no parent)
            root_categories = EFRISCommodityCategory.objects.filter(
                service_mark=service_mark,
                enable_status_code='1',
                commodity_category_level='1'  # Adjust based on your data
            ).only(
                'commodity_category_code',
                'commodity_category_name',
                'commodity_category_level',
                'is_leaf_node'
            ).order_by('commodity_category_name')[:100]  # Limit root nodes

            tree = []
            for cat in root_categories:
                # Check if it has children (without loading them)
                has_children = EFRISCommodityCategory.objects.filter(
                    parent_code=cat.commodity_category_code,
                    enable_status_code='1'
                ).exists()

                tree.append({
                    'id': cat.commodity_category_code,
                    'name': cat.commodity_category_name,
                    'level': cat.commodity_category_level,
                    'is_leaf': cat.is_leaf_node == '101',
                    'has_children': has_children,
                    'children': []  # Empty - loaded on demand
                })

            response_data = {
                'success': True,
                'tree': tree,
                'type': category_type
            }

            # Cache for 30 minutes
            cache.set(cache_key, response_data, 60 * 30)

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Error building category tree: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'Failed to load category tree'
            }, status=500)


@method_decorator(login_required, name='dispatch')
class EFRISCategoryChildrenView(View):
    """
    Get direct children of a specific category node.
    Called when user expands a tree node.
    """

    def get(self, request):
        parent_code = request.GET.get('parent_id')
        category_type = request.GET.get('type', 'product')
        service_mark = '101' if category_type == 'service' else '102'

        if not parent_code:
            return JsonResponse({'children': []})

        # Cache children for this parent
        cache_key = f'efris_children_{parent_code}_{category_type}'
        cached_children = cache.get(cache_key)

        if cached_children:
            return JsonResponse(cached_children)

        try:
            # Get direct children only
            children = EFRISCommodityCategory.objects.filter(
                parent_code=parent_code,
                service_mark=service_mark,
                enable_status_code='1'
            ).only(
                'commodity_category_code',
                'commodity_category_name',
                'commodity_category_level',
                'is_leaf_node'
            ).order_by('commodity_category_name')[:200]  # Limit children

            formatted_children = []
            for child in children:
                # Check if child has children
                has_children = EFRISCommodityCategory.objects.filter(
                    parent_code=child.commodity_category_code,
                    enable_status_code='1'
                ).exists()

                formatted_children.append({
                    'id': child.commodity_category_code,
                    'name': child.commodity_category_name,
                    'level': child.commodity_category_level,
                    'is_leaf': child.is_leaf_node == '101',
                    'has_children': has_children,
                    'children': []
                })

            response_data = {'children': formatted_children}

            # Cache for 30 minutes
            cache.set(cache_key, response_data, 60 * 30)

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Error loading children for {parent_code}: {str(e)}")
            return JsonResponse({'children': []})


@method_decorator(login_required, name='dispatch')
class EFRISCategoryResultsView(View):
    """
    Get leaf node categories under a specific parent.
    Optimized to return only selectable (leaf) categories.
    """

    def get(self, request):
        category_id = request.GET.get('category_id')
        category_type = request.GET.get('type', 'product')
        service_mark = '101' if category_type == 'service' else '102'
        limit = int(request.GET.get('limit', 50))

        logger.info(f"Loading category results for: {category_id}, type: {category_type}")

        # Cache key
        cache_key = f'efris_results_{category_id or "all"}_{category_type}_{limit}'
        cached_results = cache.get(cache_key)

        if cached_results:
            return JsonResponse(cached_results)

        try:
            # Base query for leaf nodes only
            queryset = EFRISCommodityCategory.objects.filter(
                service_mark=service_mark,
                is_leaf_node='101',
                enable_status_code='1'
            ).only(
                'commodity_category_code',
                'commodity_category_name',
                'rate',
                'is_exempt',
                'is_zero_rate',
                'commodity_category_level'
            )

            if category_id:
                # Get all leaf descendants of this category
                queryset = queryset.filter(
                    commodity_category_code__startswith=category_id
                )

            # Order and limit
            queryset = queryset.order_by('commodity_category_name')[:limit]
            results_list = list(queryset)

            # Format results
            results = [
                {
                    'code': cat.commodity_category_code,
                    'name': cat.commodity_category_name,
                    'rate': str(cat.rate) if cat.rate else '18.00',
                    'is_exempt': cat.is_exempt == '101',
                    'is_zero_rate': cat.is_zero_rate == '101',
                    'excisable': getattr(cat, 'excisable', '102') == '101',
                    'level': cat.commodity_category_level,
                }
                for cat in results_list
            ]

            response_data = {
                'success': True,
                'results': results
            }

            # Cache for 15 minutes
            cache.set(cache_key, response_data, 60 * 15)

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Error loading category results: {str(e)}")
            return JsonResponse({
                'success': False,
                'results': []
            })


@method_decorator(login_required, name='dispatch')
class EFRISPopularCategoriesView(View):
    """
    Get frequently used/popular categories.
    Pre-cached and very fast.
    """

    def get(self, request):
        category_type = request.GET.get('type', 'product')
        service_mark = '101' if category_type == 'service' else '102'
        limit = int(request.GET.get('limit', 5))

        cache_key = f'efris_popular_{category_type}_{limit}'
        cached_results = cache.get(cache_key)

        if cached_results:
            return JsonResponse(cached_results)

        try:
            # Get popular categories - could track usage in future
            # For now, return most common/generic categories
            popular_categories = EFRISCommodityCategory.objects.filter(
                service_mark=service_mark,
                is_leaf_node='101',
                enable_status_code='1'
            ).only(
                'commodity_category_code',
                'commodity_category_name',
                'rate',
                'is_exempt',
                'is_zero_rate'
            ).order_by('commodity_category_name')[:limit]

            results = [
                {
                    'code': cat.commodity_category_code,
                    'name': cat.commodity_category_name,
                    'rate': str(cat.rate) if cat.rate else '18.00',
                    'is_exempt': cat.is_exempt == '101',
                    'is_zero_rate': cat.is_zero_rate == '101',
                    'excisable': getattr(cat, 'excisable', '102') == '101',
                }
                for cat in popular_categories
            ]

            response_data = {'results': results}

            # Cache for 1 hour
            cache.set(cache_key, response_data, 60 * 60)

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Error loading popular categories: {str(e)}")
            return JsonResponse({'results': []})


@method_decorator(login_required, name='dispatch')
class EFRISCategorySearchEnhancedView(View):
    """
    Enhanced search with pagination and smart caching.
    Optimized for speed with minimal database queries.
    """

    def get(self, request):
        query = request.GET.get('q', '').strip()
        category_type = request.GET.get('type', 'product')
        page = int(request.GET.get('page', 1))
        limit = min(int(request.GET.get('limit', 25)), 50)  # Max 50 per page

        logger.info(f"Enhanced EFRIS Search - Query: '{query}', Type: {category_type}, Page: {page}")

        if len(query) < 2:
            return JsonResponse({
                'results': [],
                'total_count': 0,
                'has_more': False,
                'page': page
            })

        # Cache key for this search
        cache_key = f'efris_search_{category_type}_{query}_{page}_{limit}'
        cached_result = cache.get(cache_key)

        if cached_result:
            logger.info("Returning cached search results")
            return JsonResponse(cached_result)

        service_mark = '101' if category_type == 'service' else '102'

        try:
            # Optimized query with minimal fields
            queryset = EFRISCommodityCategory.objects.filter(
                service_mark=service_mark,
                is_leaf_node='101',
                enable_status_code='1'
            ).only(
                'commodity_category_code',
                'commodity_category_name',
                'rate',
                'is_exempt',
                'is_zero_rate',
                'commodity_category_level'
            )

            # Build search query
            queryset = queryset.filter(
                Q(commodity_category_code__icontains=query) |
                Q(commodity_category_name__icontains=query)
            )

            # Get count
            total_count = queryset.count()

            # Simple ordering for speed
            queryset = queryset.order_by('commodity_category_name')

            # Paginate
            start = (page - 1) * limit
            end = start + limit
            results = list(queryset[start:end])

            # Format results
            formatted_results = [
                {
                    'code': cat.commodity_category_code,
                    'name': cat.commodity_category_name,
                    'rate': str(cat.rate) if cat.rate else '18.00',
                    'is_exempt': cat.is_exempt == '101',
                    'is_zero_rate': cat.is_zero_rate == '101',
                    'excisable': getattr(cat, 'excisable', '102') == '101',
                    'level': cat.commodity_category_level,
                }
                for cat in results
            ]

            response_data = {
                'results': formatted_results,
                'total_count': total_count,
                'has_more': end < total_count,
                'page': page
            }

            # Cache for 10 minutes
            cache.set(cache_key, response_data, 60 * 10)

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"Enhanced search error: {str(e)}")
            return JsonResponse({
                'results': [],
                'total_count': 0,
                'has_more': False,
                'page': page
            })


@method_decorator(login_required, name='dispatch')
class CategoryDetailAPIView(View):
    """
    Get details of a user's category including EFRIS info.
    Used when selecting category in product form.
    """

    def get(self, request, pk):
        from inventory.models import Category

        # Cache user's category details
        cache_key = f'user_category_detail_{pk}'
        cached_data = cache.get(cache_key)

        if cached_data:
            return JsonResponse(cached_data)

        try:
            category = Category.objects.select_related(
                'efris_commodity_category'
            ).only(
                'id',
                'name',
                'code',
                'category_type',
                'efris_auto_sync',
                'efris_is_uploaded',
                'efris_commodity_category__commodity_category_code',
                'efris_commodity_category__commodity_category_name',
                'efris_commodity_category__rate',
                'efris_commodity_category__is_exempt',
                'efris_commodity_category__is_zero_rate'
            ).get(pk=pk)

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

            response_data = {
                'success': True,
                'id': category.id,
                'name': category.name,
                'code': category.code,
                'category_type': category.category_type,
                'efris_commodity_category': efris_data,
                'efris_auto_sync': category.efris_auto_sync,
                'efris_is_uploaded': category.efris_is_uploaded,
            }

            # Cache for 5 minutes (shorter since user data can change)
            cache.set(cache_key, response_data, 60 * 5)

            return JsonResponse(response_data)

        except Category.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Category not found'
            }, status=404)
        except Exception as e:
            logger.error(f"Error fetching category details: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'Failed to load category details'
            }, status=500)


# Utility view to clear cache if needed
@method_decorator(login_required, name='dispatch')
class ClearEFRISCacheView(View):
    """
    Clear EFRIS cache - useful after database updates.
    Should be restricted to admin users only.
    """

    def post(self, request):
        if not request.user.is_staff:
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)

        try:
            # Clear all EFRIS-related cache keys
            cache_patterns = [
                'efris_autocomplete_*',
                'efris_category_detail_*',
                'efris_category_stats_*',
                'efris_tree_root_*',
                'efris_children_*',
                'efris_results_*',
                'efris_popular_*',
                'efris_search_*',
                'user_category_detail_*',
            ]

            # Note: This is a simplified version
            # For production, use proper cache pattern deletion
            cache.clear()

            logger.info(f"EFRIS cache cleared by user: {request.user.username}")

            return JsonResponse({
                'success': True,
                'message': 'Cache cleared successfully'
            })

        except Exception as e:
            logger.error(f"Error clearing cache: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'Failed to clear cache'
            }, status=500)