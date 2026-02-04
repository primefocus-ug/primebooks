from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class ExpenseActivityMiddleware(MiddlewareMixin):
    """Track user activity on expenses"""

    def process_view(self, request, view_func, view_args, view_kwargs):
        # ✅ CHECK SCHEMA
        from django.db import connection
        schema_name = getattr(connection, 'schema_name', 'public')

        if schema_name == 'public':
            return None

        if request.user.is_authenticated and 'expenses' in request.path:
            logger.info(
                f"User {request.user.username} accessed {request.path} at {timezone.now()}"
            )
        return None


class ExpensePermissionMiddleware(MiddlewareMixin):
    """Add expense permissions to request"""

    def process_request(self, request):
        # ✅ CHECK SCHEMA
        from django.db import connection
        schema_name = getattr(connection, 'schema_name', 'public')

        if schema_name == 'public':
            return None

        if request.user.is_authenticated:
            request.can_approve_expenses = request.user.has_perm('expenses.approve_expense')
            request.can_pay_expenses = request.user.has_perm('expenses.pay_expense')
            request.can_view_all_expenses = request.user.has_perm('expenses.view_all_expenses')

        return None