"""
context_processors.py

Updated to:
  • Use user= (not created_by=) and date= (not expense_date=)
  • Use lowercase status values matching the new STATUS_CHOICES
  • Aggregate on amount_base for currency-correct totals
  • Show pending approval count for approvers (submitted + under_review)
  • Gracefully handle the PublicUser / non-tenant case without crashing
"""

import logging

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)
CustomUser = get_user_model()


def expense_context(request):
    """Inject expense-related counters and totals into every template context."""
    context = {
        'pending_expenses_count': 0,
        'expenses_to_approve_count': 0,
        'month_expenses_total': 0,
        'ocr_processing_count': 0,
    }

    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return context

    # Only run expense queries for tenant (CustomUser) accounts.
    # PublicUser or any other user type that doesn't own expenses gets zeros.
    try:
        from public_accounts.models import PublicUser
        if isinstance(user, PublicUser):
            return context
    except ImportError:
        pass  # public_accounts app not installed — proceed normally

    # Wrap in try/except so a misconfigured DB (e.g. missing migration) never
    # breaks the whole request cycle.
    try:
        from .models import Expense

        today = timezone.now().date()
        month_start = today.replace(day=1)

        # Expenses the user submitted that are still awaiting a decision
        context['pending_expenses_count'] = Expense.objects.filter(
            user=user,
            status__in=('submitted', 'under_review'),
        ).count()

        # Expenses waiting for THIS user to approve (only for approvers)
        if user.has_perm('expenses.approve_expense'):
            context['expenses_to_approve_count'] = Expense.objects.filter(
                status__in=('submitted', 'under_review'),
            ).exclude(user=user).count()

        # This month's total in base currency
        context['month_expenses_total'] = (
            Expense.objects.filter(
                user=user,
                date__gte=month_start,
                date__lte=today,
            ).aggregate(total=Sum('amount_base'))['total'] or 0
        )

        # Receipts currently being OCR-processed (uploaded but not yet done)
        context['ocr_processing_count'] = Expense.objects.filter(
            user=user,
            ocr_processed=False,
        ).exclude(receipt='').exclude(receipt=None).count()

    except Exception as exc:
        logger.warning("expense_context processor error for user %s: %s", user.pk, exc)

    return context