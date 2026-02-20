from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.db.models import Sum, Q
from decimal import Decimal
from taggit.managers import TaggableManager
from datetime import datetime, timedelta
import uuid

User = get_user_model()


class Expense(models.Model):
    """Streamlined expense tracking model"""

    PAYMENT_METHODS = [
        ('CASH', '💵 Cash'),
        ('CREDIT_CARD', '💳 Credit Card'),
        ('DEBIT_CARD', '💳 Debit Card'),
        ('BANK_TRANSFER', '🏦 Bank Transfer'),
        ('DIGITAL_WALLET', '📱 Digital Wallet'),
        ('OTHER', '📝 Other'),
    ]

    # Core Fields
    user = models.ForeignKey(User, on_delete=models.CASCADE,null=True,blank=True, related_name='expenses')

    # Financial
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    description = models.CharField(max_length=500)
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    # Organization
    tags = TaggableManager(blank=True)

    # Payment
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, blank=True)

    # Dates
    date = models.DateField(default=timezone.now)

    # Attachments
    receipt = models.FileField(upload_to='receipts/%Y/%m/', blank=True, null=True)

    # Notes
    notes = models.TextField(blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Quick flags
    is_recurring = models.BooleanField(default=False)
    is_important = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['-date']),
            models.Index(fields=['user', '-date']),
        ]

    def __str__(self):
        return f"{self.description} - ${self.amount}"


class Budget(models.Model):
    """Budget tracking with smart alerts"""
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    PERIOD_CHOICES = [
        ('daily', '📅 Daily'),
        ('weekly', '📅 Weekly'),
        ('fortnightly', '📅 Fortnightly'),
        ('monthly', '📅 Monthly'),
        ('quarterly', '📅 Quarterly'),
        ('semi_annual', '📅 6 Months'),
        ('yearly', '📅 Yearly'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='budgets')
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES)

    # Tag filtering (optional)
    tags = TaggableManager(blank=True, help_text="Filter by specific tags")

    # Alert settings
    alert_threshold = models.IntegerField(
        default=80,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Alert percentage"
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - ${self.amount} ({self.get_period_display()})"

    def get_period_dates(self):
        """Get start and end dates for current period"""
        today = timezone.now().date()

        if self.period == 'daily':
            return today, today
        elif self.period == 'weekly':
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            return start, end
        elif self.period == 'fortnightly':
            return today - timedelta(days=14), today
        elif self.period == 'monthly':
            start = today.replace(day=1)
            if today.month == 12:
                end = today.replace(day=31)
            else:
                end = (today.replace(month=today.month + 1, day=1) - timedelta(days=1))
            return start, end
        elif self.period == 'quarterly':
            quarter_month = ((today.month - 1) // 3) * 3 + 1
            start = today.replace(month=quarter_month, day=1)
            end_month = quarter_month + 2
            end = today.replace(month=end_month, day=1)
            if end_month == 12:
                end = today.replace(month=12, day=31)
            else:
                end = (today.replace(month=end_month + 1, day=1) - timedelta(days=1))
            return start, end
        elif self.period == 'semi_annual':
            return today - timedelta(days=182), today
        elif self.period == 'yearly':
            start = today.replace(month=1, day=1)
            end = today.replace(month=12, day=31)
            return start, end

        return today, today

    def get_current_spending(self):
        """Calculate current period spending"""
        start_date, end_date = self.get_period_dates()

        expenses = Expense.objects.filter(
            user=self.user,
            date__gte=start_date,
            date__lte=end_date
        )

        # Filter by tags if budget has tags
        if self.tags.exists():
            tag_names = list(self.tags.names())
            expenses = expenses.filter(tags__name__in=tag_names).distinct()

        total = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        return total

    def get_percentage_used(self):
        """Get budget usage percentage"""
        spending = self.get_current_spending()
        if self.amount > 0:
            return (spending / self.amount * 100)
        return 0

    def is_over_threshold(self):
        """Check if spending exceeded threshold"""
        return self.get_percentage_used() >= self.alert_threshold

    def get_remaining(self):
        """Get remaining budget"""
        return self.amount - self.get_current_spending()

    def get_status_color(self):
        """Get color based on usage"""
        percentage = self.get_percentage_used()
        if percentage >= 100:
            return 'danger'
        elif percentage >= self.alert_threshold:
            return 'warning'
        return 'success'