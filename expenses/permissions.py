from django.core.exceptions import PermissionDenied
from functools import wraps


def expense_owner_or_approver_required(view_func):
    """
    Decorator to check if user is the expense owner or has approval permission
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from .models import Expense

        expense_id = kwargs.get('pk')
        if expense_id:
            try:
                expense = Expense.objects.get(pk=expense_id)
                if expense.created_by == request.user or \
                        request.user.has_perm('expenses.view_all_expenses') or \
                        request.user.has_perm('expenses.approve_expense'):
                    return view_func(request, *args, **kwargs)
            except Expense.DoesNotExist:
                pass

        raise PermissionDenied

    return wrapper


def can_modify_expense(user, expense):
    """Check if user can modify the expense"""
    if expense.status != 'DRAFT':
        return False

    return expense.created_by == user


def can_approve_expense(user, expense):
    """Check if user can approve the expense"""
    if not user.has_perm('expenses.approve_expense'):
        return False

    if expense.created_by == user:
        return False

    if expense.status not in ['SUBMITTED', 'DRAFT']:
        return False

    return True


def can_pay_expense(user, expense):
    """Check if user can mark expense as paid"""
    if not user.has_perm('expenses.pay_expense'):
        return False

    if expense.status != 'APPROVED':
        return False

    return True