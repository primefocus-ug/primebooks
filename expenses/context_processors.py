from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import  Sum
from .models import Expense
from public_accounts.models import PublicUser

CustomUser = get_user_model()

def expense_context(request):
    """Add expense-related context to all templates"""
    context = {}

    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return context

    # Only tenant users have related expenses
    if isinstance(user, CustomUser):
        # Pending expenses count
        context['pending_expenses_count'] = Expense.objects.filter(
            created_by=user,
            status='SUBMITTED'
        ).count()

        # Expenses awaiting approval (for approvers)
        if user.has_perm('expenses.approve_expense'):
            context['expenses_to_approve_count'] = Expense.objects.filter(
                status='SUBMITTED'
            ).exclude(created_by=user).count()

        # This month's total
        today = timezone.now().date()
        start_of_month = today.replace(day=1)
        month_total = Expense.objects.filter(
            created_by=user,
            expense_date__gte=start_of_month,
            expense_date__lte=today
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        context['month_expenses_total'] = month_total

    # If user is PublicUser, we simply skip expense queries
    else:
        context['pending_expenses_count'] = 0
        context['expenses_to_approve_count'] = 0
        context['month_expenses_total'] = 0

    return context
