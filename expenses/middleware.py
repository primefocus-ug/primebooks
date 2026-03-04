"""
middleware.py

Changes:
  • Structured log records (dict-style) instead of f-string concatenation
  • ExpensePermissionMiddleware now also sets request.can_view_all_expenses
    and request.pending_approval_count for convenience in templates/views
  • Both middleware classes guard against missing attributes gracefully
  • Schema guard is preserved exactly as before (django-tenants compatibility)
"""

import logging

from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


def _is_tenant_schema() -> bool:
    """Return True when the current DB connection is on a tenant schema."""
    try:
        from django.db import connection
        return getattr(connection, 'schema_name', 'public') != 'public'
    except Exception:
        return True  # Assume tenant if we can't tell


class ExpenseActivityMiddleware(MiddlewareMixin):
    """
    Log every authenticated request that touches the /expenses/ path.

    Structured log record includes user, path, method, and timestamp so it
    can be parsed easily by log-aggregation tools.
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not _is_tenant_schema():
            return None

        if request.user.is_authenticated and 'expenses' in request.path:
            logger.info(
                "expense_access",
                extra={
                    'user_id': request.user.pk,
                    'username': request.user.username,
                    'path': request.path,
                    'method': request.method,
                    'timestamp': timezone.now().isoformat(),
                },
            )
        return None


class ExpensePermissionMiddleware(MiddlewareMixin):
    """
    Attach expense-related permission flags to every request so views and
    templates can check them cheaply without repeated has_perm() calls.

    Attributes set on request:
      • can_approve_expenses      bool
      • can_pay_expenses          bool
      • can_view_all_expenses     bool
      • pending_approval_count    int  (only for approvers, 0 for others)
    """

    def process_request(self, request):
        if not _is_tenant_schema():
            return None

        # Defaults — always set so templates never raise AttributeError
        request.can_approve_expenses = False
        request.can_pay_expenses = False
        request.can_view_all_expenses = False
        request.pending_approval_count = 0

        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return None

        user = request.user
        request.can_approve_expenses = user.has_perm('expenses.approve_expense')
        request.can_pay_expenses = user.has_perm('expenses.pay_expense')
        request.can_view_all_expenses = user.has_perm('expenses.view_all_expenses')

        # Pre-compute pending count for approvers so the nav badge is always fresh
        if request.can_approve_expenses:
            try:
                from .models import Expense
                request.pending_approval_count = Expense.objects.filter(
                    status__in=('submitted', 'under_review')
                ).exclude(user=user).count()
            except Exception as exc:
                logger.warning("ExpensePermissionMiddleware: could not get pending count: %s", exc)

        return None