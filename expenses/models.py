from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
from taggit.managers import TaggableManager

User = get_user_model()


class Expense(models.Model):
    # Basic fields
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True,blank=True, related_name='expenses')
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    description = models.CharField(max_length=255)
    date = models.DateField(default=timezone.now)

    # Receipt handling
    receipt = models.FileField(
        upload_to='receipts/%Y/%m/',
        blank=True,
        null=True
    )

    # Tags for organization
    tags = TaggableManager(blank=True)

    # Notes (optional, quick entry)
    notes = models.TextField(blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['-date']),
            models.Index(fields=['user', '-date']),
        ]

    def __str__(self):
        return f"{self.description} - ${self.amount} ({self.date})"

    @property
    def receipt_filename(self):
        if self.receipt:
            return self.receipt.name.split('/')[-1]
        return None


class Budget(models.Model):
    PERIOD_CHOICES = [
        ('weekly', 'Weekly'),
        ('fortnightly', 'Fortnightly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semi_annual', '6 Months'),
        ('yearly', 'Yearly'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='budgets')
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES)

    # Optional: tag-specific budgets
    tags = TaggableManager(blank=True, help_text="Leave empty for overall budget")

    # Alert settings
    alert_threshold = models.IntegerField(
        default=80,
        help_text="Alert when spending reaches this percentage"
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - ${self.amount} ({self.get_period_display()})"

    def get_current_spending(self):
        """Calculate current period spending"""
        from datetime import datetime, timedelta
        from django.db.models import Sum

        today = timezone.now().date()
        period_map = {
            'weekly': timedelta(days=7),
            'fortnightly': timedelta(days=14),
            'monthly': timedelta(days=30),
            'quarterly': timedelta(days=90),
            'semi_annual': timedelta(days=182),
            'yearly': timedelta(days=365),
        }

        start_date = today - period_map[self.period]

        expenses = Expense.objects.filter(
            user=self.user,
            date__gte=start_date,
            date__lte=today
        )

        # Filter by tags if budget is tag-specific
        if self.tags.exists():
            tag_names = list(self.tags.names())
            expenses = expenses.filter(tags__name__in=tag_names).distinct()

        total = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        return total

    def get_percentage_used(self):
        spending = self.get_current_spending()
        if self.amount > 0:
            return (spending / self.amount) * 100
        return 0

    def is_over_threshold(self):
        return self.get_percentage_used() >= self.alert_threshold