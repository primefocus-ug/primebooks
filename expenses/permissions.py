"""
permissions.py — Decorator and helper functions for the expenses app.

Changes from original:
  • expense_owner_or_approver_required checks expense.user (not created_by)
  • can_modify_expense allows editing in 'resubmit' state (not only 'draft')
  • can_approve_expense uses lowercase status values and adds self-approval guard
  • New helper: can_submit_expense
  • New helper: can_comment_on_expense
"""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def expense_owner_or_approver_required(view_func):
    """
    Allow access if the requesting user owns the expense OR has one of:
      • expenses.view_all_expenses
      • expenses.approve_expense
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from .models import Expense

        expense_id = kwargs.get('pk')
        if not expense_id:
            raise PermissionDenied

        expense = get_object_or_404(Expense, pk=expense_id)

        is_owner = expense.user_id == request.user.pk
        can_approve = request.user.has_perm('expenses.approve_expense')
        can_view_all = request.user.has_perm('expenses.view_all_expenses')

        if is_owner or can_approve or can_view_all:
            return view_func(request, *args, **kwargs)

        raise PermissionDenied

    return wrapper


def approver_required(view_func):
    """Restrict a view to users with the approve_expense permission."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.has_perm('expenses.approve_expense'):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Object-level permission helpers
# ---------------------------------------------------------------------------

def can_modify_expense(user, expense) -> bool:
    """
    The owner may edit an expense while it is in 'draft' or 'resubmit' state.
    Approvers have no reason to modify the expense body directly.
    """
    if expense.status not in ('draft', 'resubmit'):
        return False
    return expense.user_id == user.pk


def can_submit_expense(user, expense) -> bool:
    """An expense can only be submitted by its owner from draft/resubmit."""
    if expense.status not in ('draft', 'resubmit'):
        return False
    return expense.user_id == user.pk


def can_approve_expense(user, expense) -> bool:
    """
    Approval rules:
      1. User must have the approve_expense permission.
      2. A user cannot approve their own expense (self-approval guard).
      3. Only submitted or under_review expenses can be approved.
    """
    if not user.has_perm('expenses.approve_expense'):
        return False

    if expense.user_id == user.pk:
        return False  # Self-approval not allowed

    if expense.status not in ('submitted', 'under_review'):
        return False

    return True


def can_reject_expense(user, expense) -> bool:
    """Same rules as approval — rejection is also a privileged action."""
    return can_approve_expense(user, expense)


def can_comment_on_expense(user, expense) -> bool:
    """
    Both the expense owner and approvers may leave comments at any point
    in the lifecycle (useful for back-and-forth on resubmissions).
    """
    is_owner = expense.user_id == user.pk
    is_approver = user.has_perm('expenses.approve_expense')
    return is_owner or is_approver


def can_delete_expense(user, expense) -> bool:
    """Only the owner may delete, and only while the expense is a draft."""
    if expense.status != 'draft':
        return False
    return expense.user_id == user.pk