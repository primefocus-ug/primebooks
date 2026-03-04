from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.db.models import Sum, Q
from decimal import Decimal
from taggit.managers import TaggableManager
from datetime import datetime, timedelta
import uuid

from primebooks.mixins import OfflineIDMixin

User = get_user_model()


# ---------------------------------------------------------------------------
# Currency choices (ISO 4217 subset — extend as needed)
# ---------------------------------------------------------------------------
CURRENCY_CHOICES = [
    ('UGX', '🇺🇬 Ugandan Shilling'),
    ('KES', '🇰🇪 Kenyan Shilling'),
    ('TZS', '🇹🇿 Tanzanian Shilling'),
    ('USD', '🇺🇸 US Dollar'),
    ('EUR', '🇪🇺 Euro'),
    ('GBP', '🇬🇧 British Pound'),
    ('NGN', '🇳🇬 Nigerian Naira'),
    ('ZAR', '🇿🇦 South African Rand'),
    ('GHS', '🇬🇭 Ghanaian Cedi'),
    ('JPY', '🇯🇵 Japanese Yen'),
    ('CAD', '🇨🇦 Canadian Dollar'),
    ('AUD', '🇦🇺 Australian Dollar'),
    ('INR', '🇮🇳 Indian Rupee'),
    ('CNY', '🇨🇳 Chinese Yuan'),
    ('CHF', '🇨🇭 Swiss Franc'),
]


class Expense(OfflineIDMixin, models.Model):
    """Streamlined expense tracking model"""

    PAYMENT_METHODS = [
        ('CASH', '💵 Cash'),
        ('CREDIT_CARD', '💳 Credit Card'),
        ('DEBIT_CARD', '💳 Debit Card'),
        ('BANK_TRANSFER', '🏦 Bank Transfer'),
        ('DIGITAL_WALLET', '📱 Digital Wallet'),
        ('OTHER', '📝 Other'),
    ]

    STATUS_CHOICES = [
        ('draft', '📝 Draft'),
        ('submitted', '📤 Submitted'),
        ('under_review', '🔍 Under Review'),
        ('approved', '✅ Approved'),
        ('rejected', '❌ Rejected'),
        ('resubmit', '🔄 Needs Resubmission'),
    ]

    # Core Fields
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name='expenses'
    )

    # Financial
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )

    # Currency
    currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default='UGX',
        db_index=True,
    )
    # Exchange rate to the user's base/home currency at time of entry.
    # Store 1.0 when amount is already in base currency.
    exchange_rate = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        default=Decimal('1.000000'),
        help_text='Rate used to convert this expense to your base currency',
    )
    # Convenience field: amount * exchange_rate, kept in sync automatically
    amount_base = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Amount converted to base currency',
    )

    description = models.CharField(max_length=500)
    vendor = models.CharField(max_length=200, blank=True, help_text='Merchant or vendor name')

    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )

    # Organisation
    tags = TaggableManager(blank=True)

    # Payment
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, blank=True)

    # Approval workflow status (lightweight — full history in ExpenseApproval)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True
    )

    # Dates
    date = models.DateField(default=timezone.now)

    # Attachments
    receipt = models.FileField(upload_to='receipts/%Y/%m/', blank=True, null=True)

    # OCR results (populated by the Celery OCR task)
    ocr_raw = models.TextField(
        blank=True,
        help_text='Raw OCR text extracted from receipt',
    )
    ocr_vendor = models.CharField(
        max_length=200, blank=True,
        help_text='Vendor name detected by OCR',
    )
    ocr_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Amount detected by OCR',
    )
    ocr_processed = models.BooleanField(default=False)

    # Notes
    notes = models.TextField(blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Quick flags
    is_recurring = models.BooleanField(default=False)
    # How often to auto-create a copy (only used when is_recurring=True)
    RECURRENCE_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('fortnightly', 'Fortnightly'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
    ]
    recurrence_interval = models.CharField(
        max_length=15, choices=RECURRENCE_CHOICES, blank=True,
        help_text='Only used when is_recurring is True',
    )
    next_recurrence_date = models.DateField(
        null=True, blank=True,
        help_text='Date when the next copy should be auto-created',
    )
    is_important = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['-date']),
            models.Index(fields=['user', '-date']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['currency']),
        ]
        permissions = [
            ('approve_expense', 'Can approve expenses'),
        ]

    def __str__(self):
        return f"{self.description} - {self.currency} {self.amount}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def compute_amount_base(self):
        """Return amount converted to base currency."""
        return (self.amount * self.exchange_rate).quantize(Decimal('0.01'))

    def save(self, *args, **kwargs):
        # Keep amount_base in sync whenever the expense is saved
        self.amount_base = self.compute_amount_base()
        super().save(*args, **kwargs)

    def can_be_submitted(self):
        return self.status in ('draft', 'resubmit')

    def can_be_approved(self):
        return self.status in ('submitted', 'under_review')

    def can_be_rejected(self):
        return self.status in ('submitted', 'under_review')


# ---------------------------------------------------------------------------
# Approval workflow
# ---------------------------------------------------------------------------

class ExpenseApproval(models.Model):
    """
    Full audit trail of every status transition for an Expense.

    One row is written each time a status change occurs, giving a complete
    history of who did what and when.
    """

    ACTION_CHOICES = [
        ('submitted', '📤 Submitted for Approval'),
        ('under_review', '🔍 Marked Under Review'),
        ('approved', '✅ Approved'),
        ('rejected', '❌ Rejected'),
        ('resubmit', '🔄 Returned for Resubmission'),
        ('cancelled', '🚫 Cancelled'),
        ('comment', '💬 Comment Added'),
    ]

    expense = models.ForeignKey(
        Expense, on_delete=models.CASCADE, related_name='approvals'
    )
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='approval_actions'
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    comment = models.TextField(blank=True, help_text='Optional note / rejection reason')
    previous_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['expense', 'action']),
            models.Index(fields=['actor']),
        ]

    def __str__(self):
        return f"{self.expense} — {self.get_action_display()} by {self.actor} @ {self.created_at:%Y-%m-%d %H:%M}"

    # ------------------------------------------------------------------
    # Convenience factory
    # ------------------------------------------------------------------

    @classmethod
    def record(cls, expense, actor, action, comment=''):
        """Create an approval record and update the expense status accordingly."""
        STATUS_MAP = {
            'submitted': 'submitted',
            'under_review': 'under_review',
            'approved': 'approved',
            'rejected': 'rejected',
            'resubmit': 'resubmit',
            'cancelled': 'draft',
            # 'comment' does not change status
        }
        previous_status = expense.status
        new_status = STATUS_MAP.get(action, expense.status)

        record = cls.objects.create(
            expense=expense,
            actor=actor,
            action=action,
            comment=comment,
            previous_status=previous_status,
            new_status=new_status,
        )

        if new_status != previous_status:
            expense.status = new_status
            expense.save(update_fields=['status', 'updated_at'])

        return record


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

class Budget(OfflineIDMixin, models.Model):
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

    # Optional currency scope — leave blank to match all currencies
    currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        blank=True,
        help_text='Restrict to a single currency (leave blank for all)',
    )

    # Tag filtering (optional)
    tags = TaggableManager(blank=True, help_text='Filter by specific tags')

    # Alert settings
    alert_threshold = models.IntegerField(
        default=80,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text='Alert percentage'
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - {self.amount} ({self.get_period_display()})"

    # ------------------------------------------------------------------
    # Period date helpers — all bugs fixed
    # ------------------------------------------------------------------

    def get_period_dates(self):
        """Return (start_date, end_date) for the current budget period."""
        today = timezone.now().date()

        if self.period == 'daily':
            return today, today

        elif self.period == 'weekly':
            start = today - timedelta(days=today.weekday())   # Monday
            end = start + timedelta(days=6)                    # Sunday
            return start, end

        elif self.period == 'fortnightly':
            start = today - timedelta(days=13)
            return start, today

        elif self.period == 'monthly':
            start = today.replace(day=1)
            # Last day of current month — move to first of next then subtract 1 day
            if today.month == 12:
                end = today.replace(month=12, day=31)
            else:
                end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
            return start, end

        elif self.period == 'quarterly':
            # Determine the first month of the current quarter
            quarter_start_month = ((today.month - 1) // 3) * 3 + 1  # 1, 4, 7, or 10
            start = today.replace(month=quarter_start_month, day=1)

            # Last month of the quarter is quarter_start_month + 2
            quarter_end_month = quarter_start_month + 2   # 3, 6, 9, or 12

            # Last day of that month
            if quarter_end_month == 12:
                end = today.replace(month=12, day=31)
            else:
                # First day of the month AFTER the quarter end, minus 1 day
                end = today.replace(month=quarter_end_month + 1, day=1) - timedelta(days=1)

            return start, end

        elif self.period == 'semi_annual':
            start = today - timedelta(days=182)
            return start, today

        elif self.period == 'yearly':
            start = today.replace(month=1, day=1)
            end = today.replace(month=12, day=31)
            return start, end

        return today, today

    # ------------------------------------------------------------------
    # Spending helpers
    # ------------------------------------------------------------------

    def get_current_spending(self):
        """Calculate current period spending (always in base-currency amounts)."""
        start_date, end_date = self.get_period_dates()

        expenses = Expense.objects.filter(
            user=self.user,
            date__gte=start_date,
            date__lte=end_date,
        )

        # Optional currency scope
        if self.currency:
            expenses = expenses.filter(currency=self.currency)

        # Filter by tags if budget has tags
        if self.tags.exists():
            tag_names = list(self.tags.names())
            expenses = expenses.filter(tags__name__in=tag_names).distinct()

        # Sum the base-currency amount so multi-currency comparisons are fair
        total = expenses.aggregate(total=Sum('amount_base'))['total'] or Decimal('0.00')
        return total

    def get_percentage_used(self):
        """Get budget usage percentage."""
        spending = self.get_current_spending()
        if self.amount > 0:
            return spending / self.amount * 100
        return Decimal('0')

    def is_over_threshold(self):
        """Check if spending has exceeded alert threshold."""
        return self.get_percentage_used() >= self.alert_threshold

    def get_remaining(self):
        """Get remaining budget amount."""
        return self.amount - self.get_current_spending()

    def get_status_color(self):
        """Return Bootstrap colour token based on usage."""
        percentage = self.get_percentage_used()
        if percentage >= 100:
            return 'danger'
        elif percentage >= self.alert_threshold:
            return 'warning'
        return 'success'