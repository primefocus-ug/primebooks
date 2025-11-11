from django.db.models import Count, Sum
from .models import Expense


def expense_context(request):
    """Add expense-related context to all templates"""
    context = {}

    if request.user.is_authenticated:
        # Pending expenses count
        context['pending_expenses_count'] = Expense.objects.filter(
            created_by=request.user,
            status='SUBMITTED'
        ).count()

        # Expenses awaiting approval (for approvers)
        if request.user.has_perm('expenses.approve_expense'):
            context['expenses_to_approve_count'] = Expense.objects.filter(
                status='SUBMITTED'
            ).exclude(created_by=request.user).count()

        # This month's total
        from django.utils import timezone
        today = timezone.now().date()
        start_of_month = today.replace(day=1)

        month_total = Expense.objects.filter(
            created_by=request.user,
            expense_date__gte=start_of_month,
            expense_date__lte=today
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        context['month_expenses_total'] = month_total

    return context