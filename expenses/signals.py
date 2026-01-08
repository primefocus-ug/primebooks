from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib import messages
from .models import Expense, Budget


@receiver(post_save, sender=Expense)
def check_budget_alerts(sender, instance, created, **kwargs):
    """Check if any budgets have been exceeded after adding an expense"""
    if not created:
        return

    # Get all active budgets for this user
    budgets = Budget.objects.filter(user=instance.user, is_active=True)

    for budget in budgets:
        # If budget has tags, check if expense matches
        if budget.tags.exists():
            expense_tags = set(instance.tags.names())
            budget_tags = set(budget.tags.names())

            # Only check if there's overlap
            if not expense_tags.intersection(budget_tags):
                continue

        # Check if threshold reached
        if budget.is_over_threshold():
            percentage = budget.get_percentage_used()
            spending = budget.get_current_spending()

            # You can integrate with your notification system here
            # For now, we'll just pass (you can add email/SMS notifications)
            print(f"Budget alert: {budget.name} is at {percentage:.1f}% (${spending} of ${budget.amount})")