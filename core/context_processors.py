# context_processors.py
from .navigation import get_navigation_for_user, get_contextual_navigation


def navigation_context_processor(request):
    """
    Enhanced context processor to add navigation items to all templates
    with support for URL parameters
    """
    nav_items = []
    nav_context = {}

    if hasattr(request, 'user') and request.user.is_authenticated:
        # Extract navigation context from request
        nav_context = extract_nav_context_from_request(request)

        if nav_context:
            nav_items = get_contextual_navigation(request.user, request, **nav_context)
        else:
            nav_items = get_navigation_for_user(request.user, request)

    return {
        'navigation_items': nav_items,
        'nav_context': nav_context,
    }


def extract_nav_context_from_request(request):
    """
    Extract navigation context from the current request
    """
    nav_context = {}

    # Get URL kwargs if available
    if hasattr(request, 'resolver_match') and request.resolver_match:
        kwargs = request.resolver_match.kwargs
        nav_context.update(kwargs)

    # Try to get objects from request context if they exist
    # This would work if you set these in your views
    context_attrs = [
        'company', 'store', 'user_obj', 'product', 'invoice',
        'customer', 'branch', 'employee', 'order', 'report'
    ]

    for attr in context_attrs:
        if hasattr(request, attr):
            nav_context[attr] = getattr(request, attr)

    return nav_context


# Example mixin for views to add navigation context
class NavigationContextMixin:
    """
    Mixin to add navigation context to views
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add navigation context based on the view
        nav_context = self.get_navigation_context()
        if nav_context:
            context['nav_context'] = nav_context

        return context

    def get_navigation_context(self):
        """
        Override this method to provide navigation context
        """
        return {}


