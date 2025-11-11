from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db.models import Sum, Q, F,Count
from decimal import Decimal
from django.db import transaction as db_transaction
from datetime import datetime, timedelta
import uuid
import requests
import json

User = get_user_model()


# ============================================
# CURRENCY & EXCHANGE RATES
# ============================================

class Currency(models.Model):
    """Multi-currency support - Tenant specific"""
    code = models.CharField(max_length=3, db_index=True, help_text="ISO 4217 currency code")
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=10)
    decimal_places = models.PositiveSmallIntegerField(default=2)
    is_base = models.BooleanField(default=False, help_text="Base currency for tenant")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Currencies"
        ordering = ['code']
        indexes = [
            models.Index(fields=['code', 'is_active']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        if self.is_base:
            Currency.objects.exclude(pk=self.pk).update(is_base=False)
        super().save(*args, **kwargs)


class ExchangeRate(models.Model):
    """Exchange rates with auto-fetch from API"""
    from_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates_from')
    to_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates_to')
    rate = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        validators=[MinValueValidator(Decimal('0.0000000001'))]
    )
    rate_date = models.DateField(db_index=True)
    rate_type = models.CharField(
        max_length=20,
        choices=[
            ('SPOT', 'Spot Rate'),
            ('AVERAGE', 'Average Rate'),
            ('BUDGET', 'Budget Rate'),
            ('CLOSING', 'Closing Rate'),
        ],
        default='SPOT'
    )
    source = models.CharField(
        max_length=50,
        choices=[
            ('AUTO', 'Auto-fetched'),
            ('MANUAL', 'Manual Entry'),
            ('API', 'API Import'),
        ],
        default='AUTO'
    )
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['from_currency', 'to_currency', 'rate_date', 'rate_type']
        ordering = ['-rate_date']
        indexes = [
            models.Index(fields=['from_currency', 'to_currency', '-rate_date']),
            models.Index(fields=['rate_date', 'is_active']),
        ]

    def __str__(self):
        return f"{self.from_currency.code}/{self.to_currency.code}: {self.rate} on {self.rate_date}"

    @classmethod
    def get_rate(cls, from_currency, to_currency, rate_date=None, rate_type='SPOT'):
        """Get exchange rate for conversion"""
        if from_currency == to_currency:
            return Decimal('1.0')

        if not rate_date:
            rate_date = timezone.now().date()

        # Try exact date first
        rate = cls.objects.filter(
            from_currency=from_currency,
            to_currency=to_currency,
            rate_date=rate_date,
            rate_type=rate_type,
            is_active=True
        ).first()

        if rate:
            return rate.rate

        # Get most recent rate before date
        rate = cls.objects.filter(
            from_currency=from_currency,
            to_currency=to_currency,
            rate_date__lte=rate_date,
            rate_type=rate_type,
            is_active=True
        ).order_by('-rate_date').first()

        if rate:
            return rate.rate

        # Try inverse rate
        inverse = cls.objects.filter(
            from_currency=to_currency,
            to_currency=from_currency,
            rate_date__lte=rate_date,
            rate_type=rate_type,
            is_active=True
        ).order_by('-rate_date').first()

        if inverse:
            return Decimal('1.0') / inverse.rate

        raise ValidationError(
            f"No exchange rate found for {from_currency.code}/{to_currency.code} on {rate_date}"
        )

    @classmethod
    def convert_amount(cls, amount, from_currency, to_currency, rate_date=None, rate_type='SPOT'):
        """Convert amount from one currency to another"""
        if from_currency == to_currency:
            return amount

        rate = cls.get_rate(from_currency, to_currency, rate_date, rate_type)
        return amount * rate

    @classmethod
    def fetch_rates_from_api(cls, date=None):
        """Fetch exchange rates from external API"""
        if not date:
            date = timezone.now().date()

        try:
            base_currency = Currency.objects.filter(is_base=True).first()
            if not base_currency:
                return False

            # Using exchangerate-api.com (free tier available)
            url = f"https://api.exchangerate-api.com/v4/latest/{base_currency.code}"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                rates = data.get('rates', {})

                for currency_code, rate_value in rates.items():
                    try:
                        to_currency = Currency.objects.get(code=currency_code, is_active=True)

                        cls.objects.update_or_create(
                            from_currency=base_currency,
                            to_currency=to_currency,
                            rate_date=date,
                            rate_type='SPOT',
                            defaults={
                                'rate': Decimal(str(rate_value)),
                                'source': 'AUTO',
                                'is_active': True
                            }
                        )
                    except Currency.DoesNotExist:
                        continue

                return True
        except Exception as e:
            print(f"Error fetching exchange rates: {str(e)}")
            return False


# ============================================
# EXPENSE MANAGEMENT MODELS
# ============================================

class ExpenseCategory(models.Model):
    """Categories for organizing expenses"""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)
    gl_account = models.ForeignKey('ChartOfAccounts', on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Expense Categories"
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"


class Expense(models.Model):
    """Individual expense records for cash purchases"""

    EXPENSE_STATUS = [
        ('DRAFT', 'Draft'),
        ('SUBMITTED', 'Submitted'),
        ('APPROVED', 'Approved'),
        ('PAID', 'Paid'),
        ('REJECTED', 'Rejected'),
    ]

    PAYMENT_METHOD = [
        ('CASH', 'Cash'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('CHEQUE', 'Cheque'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('CREDIT_CARD', 'Credit Card'),
    ]

    # Basic info
    expense_number = models.CharField(max_length=50, unique=True)
    date = models.DateField(default=timezone.now)
    category = models.ForeignKey('ExpenseCategory', on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    currency = models.ForeignKey('Currency', on_delete=models.PROTECT)
    description = models.TextField()

    # Payment source
    paid_from_petty_cash = models.ForeignKey(
        'PettyCash',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="If paid from petty cash fund"
    )

    # Payment details
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD, default='CASH')
    paid_from_account = models.ForeignKey(
        'BankAccount',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Bank account used for payment (if not cash)"
    )

    # Receipt tracking
    receipt_number = models.CharField(max_length=100, blank=True)
    receipt_date = models.DateField(null=True, blank=True)
    vendor = models.CharField(max_length=200, blank=True)

    # Approval workflow
    status = models.CharField(max_length=20, choices=EXPENSE_STATUS, default='DRAFT')
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='expenses_submitted'
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expenses_approved'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, help_text="Reason for rejection if applicable")

    # Dimensions
    dimension_values = models.ManyToManyField('DimensionValue', blank=True)

    # GL Integration
    journal_entry = models.ForeignKey(
        'JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['status', 'date']),
            models.Index(fields=['expense_number']),
            models.Index(fields=['submitted_by', 'date']),
            models.Index(fields=['category', 'date']),
        ]

    def __str__(self):
        return f"{self.expense_number} - {self.description}"

    def save(self, *args, **kwargs):
        if not self.expense_number:
            self.expense_number = f"EXP-{timezone.now().strftime('%Y%m%d%H%M%S')}"

        # Auto-set submitted_at when status changes to SUBMITTED
        if self.pk:  # Only for existing instances
            original = Expense.objects.get(pk=self.pk)
            if original.status != 'SUBMITTED' and self.status == 'SUBMITTED':
                self.submitted_at = timezone.now()
        elif self.status == 'SUBMITTED':  # For new instances
            self.submitted_at = timezone.now()

        super().save(*args, **kwargs)

    def clean(self):
        """Validate expense before saving"""
        errors = {}

        # Validate payment method consistency
        if self.payment_method == 'CASH' and self.paid_from_account:
            errors['paid_from_account'] = 'Cash expenses should not have a bank account selected.'

        if self.payment_method != 'CASH' and not self.paid_from_account:
            errors['paid_from_account'] = 'Non-cash expenses require a bank account.'

        # Validate petty cash
        if self.paid_from_petty_cash and self.payment_method != 'CASH':
            errors['paid_from_petty_cash'] = 'Petty cash can only be used for cash payments.'

        if self.paid_from_petty_cash and self.paid_from_account:
            errors['paid_from_petty_cash'] = 'Cannot use both petty cash and bank account.'

        # Validate dates
        if self.receipt_date and self.receipt_date > timezone.now().date():
            errors['receipt_date'] = 'Receipt date cannot be in the future.'

        if self.receipt_date and self.receipt_date < self.date:
            errors['receipt_date'] = 'Receipt date cannot be before expense date.'

        # Validate amount
        if self.amount <= 0:
            errors['amount'] = 'Amount must be greater than zero.'

        if errors:
            raise ValidationError(errors)

    def can_submit(self):
        """Check if expense can be submitted"""
        return self.status == 'DRAFT'

    def can_approve(self):
        """Check if expense can be approved"""
        return self.status == 'SUBMITTED'

    def can_edit(self):
        """Check if expense can be edited"""
        return self.status in ['DRAFT', 'REJECTED']

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('finance:expense_detail', kwargs={'pk': self.pk})

    def create_journal_entry(self):
        """Create journal entry for approved expense"""
        if self.journal_entry:
            return self.journal_entry

        if self.status != 'APPROVED':
            raise ValidationError("Cannot create journal entry for unapproved expense")

        journal = Journal.objects.filter(journal_type=JournalType.CASH_PAYMENTS, is_active=True).first()
        if not journal:
            journal = Journal.objects.filter(journal_type=JournalType.GENERAL, is_active=True).first()

        # Use transaction to ensure data consistency
        with db_transaction.atomic():
            entry = JournalEntry.objects.create(
                journal=journal,
                entry_number=journal.get_next_entry_number(),
                entry_date=self.date,
                description=f"Expense: {self.description}",
                currency=self.currency,
                created_by=self.submitted_by,
                source_model='finance.Expense',
                source_id=str(self.pk)
            )

            # Debit: Expense account
            debit_line = JournalEntryLine.objects.create(
                journal_entry=entry,
                account=self.category.gl_account,
                debit_amount=self.amount,
                description=self.description,
                currency=self.currency,
                line_number=1
            )

            # Credit: Determine credit account
            if self.paid_from_petty_cash:
                # Credit: Petty Cash account
                credit_account = self.paid_from_petty_cash.gl_account
                credit_description = f"Petty Cash: {self.paid_from_petty_cash.name}"

                # Update petty cash balance
                self.paid_from_petty_cash.current_balance -= self.amount
                self.paid_from_petty_cash.save()

            elif self.payment_method == 'CASH' and not self.paid_from_account:
                # Use general cash account
                cash_account = ChartOfAccounts.objects.filter(
                    name__icontains='cash',
                    account_type=AccountType.ASSET,
                    is_active=True
                ).first()
                if not cash_account:
                    raise ValidationError("No cash account found. Please configure a cash account.")
                credit_account = cash_account
                credit_description = "Cash Payment"

            else:
                # Use bank account
                credit_account = self.paid_from_account.gl_account
                credit_description = f"Bank: {self.paid_from_account.account_number}"

            credit_line = JournalEntryLine.objects.create(
                journal_entry=entry,
                account=credit_account,
                credit_amount=self.amount,
                description=credit_description,
                currency=self.currency,
                line_number=2
            )

            # Add dimensions to both lines
            for dim_value in self.dimension_values.all():
                debit_line.dimension_values.add(dim_value)
                credit_line.dimension_values.add(dim_value)

            entry.calculate_totals()

            # Validate the entry is balanced before posting
            if not entry.is_balanced():
                entry.delete()  # Clean up the incomplete entry
                raise ValidationError("Journal entry is not balanced. Please check account configurations.")

            entry.post(self.approved_by or self.submitted_by)

            self.journal_entry = entry
            self.status = 'PAID'  # Mark as paid once journal entry is created
            self.save()

        return entry

    @property
    def has_receipt(self):
        """Check if expense has receipt attached"""
        return bool(self.receipt_number) or self.receipts.exists()

    @property
    def is_approved(self):
        """Check if expense is approved"""
        return self.status in ['APPROVED', 'PAID']

    @property
    def is_pending_approval(self):
        """Check if expense is waiting for approval"""
        return self.status == 'SUBMITTED'

    @classmethod
    def get_monthly_summary(cls, year, month, user=None):
        """Get monthly expense summary"""
        queryset = cls.objects.filter(
            date__year=year,
            date__month=month,
            status__in=['APPROVED', 'PAID']
        )

        if user:
            queryset = queryset.filter(submitted_by=user)

        return queryset.aggregate(
            total_amount=Sum('amount'),
            count=Count('id')
        )


class PettyCash(models.Model):
    """Petty cash fund management"""
    name = models.CharField(max_length=100)
    custodian = models.ForeignKey(User, on_delete=models.PROTECT, related_name='petty_cash_funds')
    gl_account = models.ForeignKey('ChartOfAccounts', on_delete=models.PROTECT)
    max_amount = models.DecimalField(max_digits=12, decimal_places=2)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.custodian.get_full_name()}"

    def get_available_balance(self):
        """Get available balance for spending"""
        pending_expenses = Expense.objects.filter(
            paid_from_petty_cash=self,
            status__in=['DRAFT', 'SUBMITTED']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        return self.current_balance - pending_expenses


class Receipt(models.Model):
    """Receipt/image storage for expenses"""
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='receipts')
    image = models.ImageField(upload_to='expense_receipts/')
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE,related_name='finance_receipts_uploaded')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Receipt for {self.expense.expense_number}"

# ============================================
# DIMENSIONS (Multi-dimensional Reporting)
# ============================================

class Dimension(models.Model):
    """Dimensions for multi-dimensional reporting"""
    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    dimension_type = models.CharField(
        max_length=20,
        choices=[
            ('DEPARTMENT', 'Department'),
            ('LOCATION', 'Location'),
            ('PROJECT', 'Project'),
            ('PRODUCT', 'Product Line'),
            ('CUSTOMER', 'Customer Segment'),
            ('COST_CENTER', 'Cost Center'),
            ('PROFIT_CENTER', 'Profit Center'),
            ('CUSTOM', 'Custom Dimension'),
        ]
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )
    level = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    require_for_posting = models.BooleanField(
        default=False,
        help_text="Require this dimension when posting entries"
    )

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['dimension_type', 'code']
        indexes = [
            models.Index(fields=['dimension_type', 'is_active']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        if self.parent:
            self.level = self.parent.level + 1
        else:
            self.level = 0
        super().save(*args, **kwargs)


class DimensionValue(models.Model):
    """Values for each dimension"""
    dimension = models.ForeignKey(Dimension, on_delete=models.CASCADE, related_name='values')
    code = models.CharField(max_length=20, db_index=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )
    manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_dimensions'
    )
    is_active = models.BooleanField(default=True)

    # Budget allocation
    budget_allocation_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['dimension', 'code']
        ordering = ['dimension', 'code']
        indexes = [
            models.Index(fields=['dimension', 'is_active']),
        ]

    def __str__(self):
        return f"{self.dimension.code}: {self.code} - {self.name}"


# ============================================
# CHART OF ACCOUNTS
# ============================================

class AccountType(models.TextChoices):
    ASSET = 'ASSET', _('Asset')
    LIABILITY = 'LIABILITY', _('Liability')
    EQUITY = 'EQUITY', _('Equity')
    REVENUE = 'REVENUE', _('Revenue')
    EXPENSE = 'EXPENSE', _('Expense')
    COST_OF_SALES = 'COGS', _('Cost of Goods Sold')


class ChartOfAccounts(models.Model):
    """Enhanced Chart of Accounts with multi-currency and dimensions"""
    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    account_type = models.CharField(max_length=20, choices=AccountType.choices, db_index=True)

    # Hierarchy
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )
    level = models.PositiveSmallIntegerField(default=0)
    is_header = models.BooleanField(
        default=False,
        help_text="Header accounts cannot have transactions"
    )

    # Multi-currency
    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name='accounts'
    )
    allow_multi_currency = models.BooleanField(
        default=False,
        help_text="Allow transactions in other currencies"
    )
    revaluation_account = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='revaluation_for',
        help_text="Account for currency revaluation gains/losses"
    )

    # Balances (cached for performance)
    current_balance = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00')
    )
    current_balance_base = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Balance in base currency"
    )

    # Control settings
    require_dimensions = models.ManyToManyField(
        Dimension,
        blank=True,
        help_text="Required dimensions for this account"
    )
    allow_direct_posting = models.BooleanField(
        default=True,
        help_text="Allow direct posting"
    )
    is_reconcilable = models.BooleanField(
        default=False,
        help_text="Requires reconciliation"
    )
    is_control_account = models.BooleanField(
        default=False,
        help_text="Control account (AR/AP)"
    )

    # Status
    is_active = models.BooleanField(default=True, db_index=True)
    is_system = models.BooleanField(
        default=False,
        help_text="System account, cannot be deleted"
    )

    # Tax
    tax_code = models.ForeignKey(
        'TaxCode',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accounts'
    )

    # Audit
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='accounts_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Chart of Accounts"
        verbose_name_plural = "Chart of Accounts"
        ordering = ['code']
        indexes = [
            models.Index(fields=['account_type', 'is_active']),
            models.Index(fields=['parent', 'is_active']),
            models.Index(fields=['is_active', 'is_header']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def is_debit_account(self):
        return self.account_type in [AccountType.ASSET, AccountType.EXPENSE, AccountType.COST_OF_SALES]

    @property
    def is_credit_account(self):
        return not self.is_debit_account

    def get_balance(self, as_of_date=None, currency=None, dimensions=None):
        """Get account balance with filters"""
        filters = Q(account=self, journal_entry__status='POSTED')

        if as_of_date:
            filters &= Q(journal_entry__posting_date__lte=as_of_date)

        if dimensions:
            for dim_value in dimensions:
                filters &= Q(dimension_values=dim_value)

        lines = JournalEntryLine.objects.filter(filters)

        totals = lines.aggregate(
            total_debit=Sum('debit_amount'),
            total_credit=Sum('credit_amount'),
            total_debit_base=Sum('debit_amount_base'),
            total_credit_base=Sum('credit_amount_base')
        )

        debit = totals['total_debit'] or Decimal('0')
        credit = totals['total_credit'] or Decimal('0')
        debit_base = totals['total_debit_base'] or Decimal('0')
        credit_base = totals['total_credit_base'] or Decimal('0')

        # Return in requested currency
        if currency and currency != self.currency:
            if self.is_debit_account:
                return debit_base - credit_base
            else:
                return credit_base - debit_base
        else:
            if self.is_debit_account:
                return debit - credit
            else:
                return credit - debit

    def update_balance(self):
        """Update cached balance"""
        self.current_balance = self.get_balance()
        base_currency = Currency.objects.filter(is_base=True).first()
        if base_currency:
            self.current_balance_base = self.get_balance(currency=base_currency)
        self.save(update_fields=['current_balance', 'current_balance_base'])

    def clean(self):
        if self.is_header and JournalEntryLine.objects.filter(account=self).exists():
            raise ValidationError("Cannot convert to header: transactions exist")

        # Prevent circular references
        if self.parent:
            parent = self.parent
            while parent:
                if parent == self:
                    raise ValidationError("Circular parent reference")
                parent = parent.parent

    def save(self, *args, **kwargs):
        if self.parent:
            self.level = self.parent.level + 1
        else:
            self.level = 0
        super().save(*args, **kwargs)


# ============================================
# FISCAL YEAR & PERIODS
# ============================================

class FiscalYear(models.Model):
    """Tenant-specific fiscal years"""
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True, db_index=True)
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)

    status = models.CharField(
        max_length=20,
        choices=[
            ('FUTURE', 'Future'),
            ('OPEN', 'Open'),
            ('CLOSED', 'Closed'),
            ('LOCKED', 'Locked'),
        ],
        default='FUTURE',
        db_index=True
    )
    is_current = models.BooleanField(default=False, db_index=True)

    number_of_periods = models.PositiveSmallIntegerField(default=12)
    period_type = models.CharField(
        max_length=20,
        choices=[
            ('MONTHLY', 'Monthly'),
            ('QUARTERLY', 'Quarterly'),
            ('CUSTOM', 'Custom'),
        ],
        default='MONTHLY'
    )

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fiscal_years_closed'
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['status', 'is_current']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_current:
            FiscalYear.objects.exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)

    def generate_periods(self):
        """Generate fiscal periods automatically"""
        if self.periods.exists():
            raise ValidationError("Periods already exist for this fiscal year")

        if self.period_type == 'MONTHLY':
            self._generate_monthly_periods()
        elif self.period_type == 'QUARTERLY':
            self._generate_quarterly_periods()

    def _generate_monthly_periods(self):
        """Generate monthly periods"""
        current_date = self.start_date
        period_num = 1

        while current_date <= self.end_date:
            # Calculate period end (last day of month or fiscal year end)
            if current_date.month == 12:
                period_end = current_date.replace(day=31)
            else:
                next_month = current_date.replace(month=current_date.month + 1, day=1)
                period_end = next_month - timedelta(days=1)

            if period_end > self.end_date:
                period_end = self.end_date

            FiscalPeriod.objects.create(
                fiscal_year=self,
                name=current_date.strftime('%B %Y'),
                code=f"{self.code}-P{period_num:02d}",
                period_number=period_num,
                start_date=current_date,
                end_date=period_end,
                status='FUTURE' if current_date > timezone.now().date() else 'OPEN'
            )

            period_num += 1
            current_date = period_end + timedelta(days=1)

    def _generate_quarterly_periods(self):
        """Generate quarterly periods"""
        quarters = []
        current_date = self.start_date

        for i in range(4):
            quarter_months = 3
            period_end = current_date

            for _ in range(quarter_months - 1):
                if period_end.month == 12:
                    period_end = period_end.replace(year=period_end.year + 1, month=1)
                else:
                    period_end = period_end.replace(month=period_end.month + 1)

            # Last day of quarter
            if period_end.month in [3, 6, 9, 12]:
                period_end = period_end.replace(day=30 if period_end.month in [6, 9] else 31)

            if period_end > self.end_date:
                period_end = self.end_date

            FiscalPeriod.objects.create(
                fiscal_year=self,
                name=f"Q{i + 1} {self.name}",
                code=f"{self.code}-Q{i + 1}",
                period_number=i + 1,
                start_date=current_date,
                end_date=period_end,
                status='FUTURE' if current_date > timezone.now().date() else 'OPEN'
            )

            current_date = period_end + timedelta(days=1)

    def close_year(self, user):
        """Close fiscal year"""
        if self.status == 'CLOSED':
            raise ValidationError("Fiscal year already closed")

        open_periods = self.periods.exclude(status__in=['CLOSED', 'LOCKED']).count()
        if open_periods > 0:
            raise ValidationError(f"Cannot close year: {open_periods} periods still open")

        self.status = 'CLOSED'
        self.closed_by = user
        self.closed_at = timezone.now()
        self.save()


class FiscalPeriod(models.Model):
    """Fiscal periods"""
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name='periods')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, db_index=True)
    period_number = models.PositiveSmallIntegerField()
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)

    status = models.CharField(
        max_length=20,
        choices=[
            ('FUTURE', 'Future'),
            ('OPEN', 'Open'),
            ('CLOSED', 'Closed'),
            ('LOCKED', 'Locked'),
        ],
        default='FUTURE',
        db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='periods_closed'
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['fiscal_year', 'period_number']
        ordering = ['fiscal_year', 'period_number']
        indexes = [
            models.Index(fields=['fiscal_year', 'status']),
            models.Index(fields=['start_date', 'end_date']),
        ]

    def __str__(self):
        return f"{self.fiscal_year.name} - {self.name}"

    def close_period(self, user):
        """Close period with validations"""
        if self.status == 'CLOSED':
            raise ValidationError("Period already closed")

        unposted = JournalEntry.objects.filter(
            fiscal_period=self,
            status__in=['DRAFT', 'PENDING']
        ).count()

        if unposted > 0:
            raise ValidationError(f"Cannot close: {unposted} unposted entries exist")

        self.status = 'CLOSED'
        self.closed_by = user
        self.closed_at = timezone.now()
        self.save()


# ============================================
# JOURNALS & ENTRIES
# ============================================

class JournalType(models.TextChoices):
    GENERAL = 'GENERAL', _('General Journal')
    SALES = 'SALES', _('Sales Journal')
    PURCHASE = 'PURCHASE', _('Purchase Journal')
    CASH_RECEIPTS = 'CASH_RECEIPTS', _('Cash Receipts')
    CASH_PAYMENTS = 'CASH_PAYMENTS', _('Cash Payments')
    PAYROLL = 'PAYROLL', _('Payroll Journal')
    DEPRECIATION = 'DEPRECIATION', _('Depreciation Journal')
    ADJUSTMENT = 'ADJUSTMENT', _('Adjusting Journal')
    CLOSING = 'CLOSING', _('Closing Journal')
    RECURRING = 'RECURRING', _('Recurring Journal')


class Journal(models.Model):
    """Journal definition"""
    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    journal_type = models.CharField(max_length=20, choices=JournalType.choices)
    description = models.TextField(blank=True)

    # Numbering
    prefix = models.CharField(max_length=10, blank=True)
    next_number = models.PositiveIntegerField(default=1)
    number_padding = models.PositiveSmallIntegerField(default=6)

    # Control
    require_approval = models.BooleanField(default=False)
    approval_limit = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Entries above this require approval"
    )
    auto_approval_limit = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Auto-approve below this amount"
    )

    allowed_dimensions = models.ManyToManyField(Dimension, blank=True)
    default_debit_account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journals_debit_default'
    )
    default_credit_account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journals_credit_default'
    )

    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def get_next_entry_number(self):
        """Generate next entry number (thread-safe)"""
        from django.db import transaction
        with transaction.atomic():
            journal = Journal.objects.select_for_update().get(pk=self.pk)
            number = str(journal.next_number).zfill(journal.number_padding)
            entry_number = f"{journal.prefix}{number}"
            journal.next_number += 1
            journal.save(update_fields=['next_number'])
            return entry_number


class JournalEntry(models.Model):
    """Enhanced Journal Entry with multi-currency"""

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('POSTED', 'Posted'),
        ('REVERSED', 'Reversed'),
        ('CANCELLED', 'Cancelled'),
    ]

    # Identity
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry_number = models.CharField(max_length=50, unique=True, db_index=True)
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name='entries')

    # Dates
    entry_date = models.DateField(db_index=True)
    posting_date = models.DateField(null=True, blank=True, db_index=True)
    reversal_date = models.DateField(null=True, blank=True)

    # Period
    fiscal_year = models.ForeignKey(
        FiscalYear,
        on_delete=models.PROTECT,
        related_name='journal_entries'
    )
    fiscal_period = models.ForeignKey(
        FiscalPeriod,
        on_delete=models.PROTECT,
        related_name='journal_entries'
    )

    # Description
    reference = models.CharField(max_length=100, blank=True, db_index=True)
    description = models.TextField()
    notes = models.TextField(blank=True)

    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT',
        db_index=True
    )

    # Currency
    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name='journal_entries',
        help_text="Entry currency"
    )
    exchange_rate = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        default=Decimal('1.0')
    )

    # Totals (cached)
    total_debit = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
    total_credit = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
    total_debit_base = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
    total_credit_base = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))

    # Reversal tracking
    is_reversal = models.BooleanField(default=False)
    reverses_entry = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversed_by'
    )

    # Source tracking
    source_model = models.CharField(max_length=100, blank=True)
    source_id = models.CharField(max_length=100, blank=True)

    # Approval workflow
    requires_approval = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_entries_approved'
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Audit
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='journal_entries_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    posted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_entries_posted'
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "Journal Entries"
        ordering = ['-entry_date', '-created_at']
        indexes = [
            models.Index(fields=['status', 'entry_date']),
            models.Index(fields=['fiscal_period', 'status']),
            models.Index(fields=['journal', 'status']),
            models.Index(fields=['source_model', 'source_id']),
        ]

    def __str__(self):
        return f"{self.entry_number} - {self.description[:50]}"

    def is_balanced(self):
        """Check if entry is balanced"""
        return abs(self.total_debit - self.total_credit) < Decimal('0.01')

    def calculate_totals(self):
        """Calculate and cache totals"""
        lines = self.lines.all()
        self.total_debit = sum(line.debit_amount for line in lines)
        self.total_credit = sum(line.credit_amount for line in lines)
        self.total_debit_base = sum(line.debit_amount_base for line in lines)
        self.total_credit_base = sum(line.credit_amount_base for line in lines)
        self.save(update_fields=['total_debit', 'total_credit', 'total_debit_base', 'total_credit_base'])

    def post(self, user):
        """Post journal entry"""
        if self.status == 'POSTED':
            raise ValidationError("Entry already posted")

        if self.status == 'CANCELLED':
            raise ValidationError("Cannot post cancelled entry")

        if not self.is_balanced():
            raise ValidationError("Entry is not balanced")

        # Check period status
        if self.fiscal_period.status not in ['OPEN', 'FUTURE']:
            raise ValidationError(f"Cannot post to {self.fiscal_period.status} period")

        # Check approval requirement
        if self.requires_approval and self.status != 'APPROVED':
            raise ValidationError("Entry requires approval before posting")

        # Validate lines
        for line in self.lines.all():
            line.validate_posting()

        self.status = 'POSTED'
        self.posting_date = timezone.now().date()
        self.posted_by = user
        self.posted_at = timezone.now()
        self.save()

        # Update account balances
        for line in self.lines.all():
            line.account.update_balance()

    def reverse(self, user, reversal_date=None, description=None):
        """Create reversal entry"""
        if self.status != 'POSTED':
            raise ValidationError("Only posted entries can be reversed")

        if self.is_reversal:
            raise ValidationError("Cannot reverse a reversal entry")

        if not reversal_date:
            reversal_date = timezone.now().date()

        # Get fiscal period for reversal date
        fiscal_period = FiscalPeriod.objects.filter(
            start_date__lte=reversal_date,
            end_date__gte=reversal_date,
            status='OPEN'
        ).first()

        if not fiscal_period:
            raise ValidationError(f"No open period found for {reversal_date}")

        # Create reversal entry
        reversal = JournalEntry.objects.create(
            journal=self.journal,
            entry_number=self.journal.get_next_entry_number(),
            entry_date=reversal_date,
            fiscal_year=fiscal_period.fiscal_year,
            fiscal_period=fiscal_period,
            description=description or f"Reversal of {self.entry_number}",
            reference=f"REV-{self.entry_number}",
            currency=self.currency,
            exchange_rate=self.exchange_rate,
            is_reversal=True,
            reverses_entry=self,
            created_by=user
        )

        # Create reversal lines (swap debit/credit)
        for line in self.lines.all():
            JournalEntryLine.objects.create(
                journal_entry=reversal,
                account=line.account,
                description=f"Reversal: {line.description}",
                debit_amount=line.credit_amount,
                credit_amount=line.debit_amount,
                debit_amount_base=line.credit_amount_base,
                credit_amount_base=line.debit_amount_base,
                currency=line.currency,
                exchange_rate=line.exchange_rate
            )

            # Copy dimensions
            for dim_value in line.dimension_values.all():
                reversal.lines.last().dimension_values.add(dim_value)

        reversal.calculate_totals()
        reversal.post(user)

        # Mark original as reversed
        self.status = 'REVERSED'
        self.reversal_date = reversal_date
        self.save()

        return reversal

    def approve(self, user):
        """Approve entry"""
        if self.status != 'PENDING':
            raise ValidationError("Entry is not pending approval")

        self.status = 'APPROVED'
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save()

    def cancel(self, user):
        """Cancel draft entry"""
        if self.status not in ['DRAFT', 'PENDING']:
            raise ValidationError("Only draft/pending entries can be cancelled")

        self.status = 'CANCELLED'
        self.save()


class JournalEntryLine(models.Model):
    """Journal entry line with multi-currency and dimensions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines')
    line_number = models.PositiveSmallIntegerField(default=1)

    # Account
    account = models.ForeignKey(ChartOfAccounts, on_delete=models.PROTECT, related_name='journal_lines')
    description = models.CharField(max_length=500, blank=True)

    # Amounts in transaction currency
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name='journal_lines')
    debit_amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(0)]
    )
    credit_amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(0)]
    )

    # Amounts in base currency
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=10, default=Decimal('1.0'))
    debit_amount_base = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
    credit_amount_base = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))

    # Multi-dimensional reporting
    dimension_values = models.ManyToManyField(DimensionValue, blank=True, related_name='journal_lines')

    # Tax
    tax_code = models.ForeignKey('TaxCode', on_delete=models.SET_NULL, null=True, blank=True)
    tax_amount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))

    # Quantity (for unit-based tracking)
    quantity = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Quantity for statistical tracking"
    )
    unit_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['journal_entry', 'line_number']
        indexes = [
            models.Index(fields=['journal_entry', 'line_number']),
            models.Index(fields=['account', 'journal_entry']),
        ]

    def __str__(self):
        return f"{self.journal_entry.entry_number} - Line {self.line_number}"

    def save(self, *args, **kwargs):
        # Calculate base currency amounts
        if self.currency != self.journal_entry.currency:
            base_currency = Currency.objects.filter(is_base=True).first()
            if base_currency:
                self.debit_amount_base = ExchangeRate.convert_amount(
                    self.debit_amount,
                    self.currency,
                    base_currency,
                    self.journal_entry.entry_date
                )
                self.credit_amount_base = ExchangeRate.convert_amount(
                    self.credit_amount,
                    self.currency,
                    base_currency,
                    self.journal_entry.entry_date
                )
        else:
            self.debit_amount_base = self.debit_amount
            self.credit_amount_base = self.credit_amount

        super().save(*args, **kwargs)

    def validate_posting(self):
        """Validate before posting"""
        # Check account allows posting
        if not self.account.allow_direct_posting:
            raise ValidationError(f"Account {self.account.code} does not allow direct posting")

        if self.account.is_header:
            raise ValidationError(f"Cannot post to header account {self.account.code}")

        # Check required dimensions
        required_dims = self.account.require_dimensions.all()
        line_dims = [dv.dimension for dv in self.dimension_values.all()]

        for dim in required_dims:
            if dim not in line_dims:
                raise ValidationError(f"Dimension {dim.name} is required for account {self.account.code}")

        # Ensure only debit or credit, not both
        if self.debit_amount > 0 and self.credit_amount > 0:
            raise ValidationError("Line cannot have both debit and credit amounts")


# ============================================
# RECURRING JOURNAL ENTRIES (Automation)
# ============================================

class RecurringJournalEntry(models.Model):
    """Automated recurring journal entries"""

    FREQUENCY_CHOICES = [
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('BIWEEKLY', 'Bi-weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('SEMI_ANNUAL', 'Semi-annual'),
        ('ANNUAL', 'Annual'),
    ]

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField()
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name='recurring_entries')

    # Schedule
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text="Leave blank for indefinite")
    next_run_date = models.DateField(db_index=True)
    last_run_date = models.DateField(null=True, blank=True)

    # Template
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    template_data = models.JSONField(
        help_text="JSON template for recurring entry lines"
    )

    # Control
    auto_post = models.BooleanField(
        default=False,
        help_text="Automatically post generated entries"
    )
    is_active = models.BooleanField(default=True)

    # Audit
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Recurring Journal Entries"
        ordering = ['name']
        indexes = [
            models.Index(fields=['next_run_date', 'is_active']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def generate_entry(self):
        """Generate journal entry from template"""
        if not self.is_active:
            raise ValidationError("Recurring entry is not active")

        if self.end_date and self.next_run_date > self.end_date:
            raise ValidationError("Recurring entry has ended")

        # Get fiscal period for next run date
        fiscal_period = FiscalPeriod.objects.filter(
            start_date__lte=self.next_run_date,
            end_date__gte=self.next_run_date,
            status='OPEN'
        ).first()

        if not fiscal_period:
            raise ValidationError(f"No open period for {self.next_run_date}")

        # Create entry
        entry = JournalEntry.objects.create(
            journal=self.journal,
            entry_number=self.journal.get_next_entry_number(),
            entry_date=self.next_run_date,
            fiscal_year=fiscal_period.fiscal_year,
            fiscal_period=fiscal_period,
            description=f"{self.description} - {self.next_run_date}",
            reference=f"REC-{self.code}",
            currency=self.currency,
            created_by=self.created_by,
            source_model='finance.RecurringJournalEntry',
            source_id=str(self.pk)
        )

        # Create lines from template
        for line_data in self.template_data.get('lines', []):
            account = ChartOfAccounts.objects.get(code=line_data['account_code'])

            line = JournalEntryLine.objects.create(
                journal_entry=entry,
                account=account,
                description=line_data.get('description', ''),
                debit_amount=Decimal(str(line_data.get('debit', 0))),
                credit_amount=Decimal(str(line_data.get('credit', 0))),
                currency=self.currency
            )

            # Add dimensions if specified
            if 'dimensions' in line_data:
                for dim_code in line_data['dimensions']:
                    dim_value = DimensionValue.objects.get(code=dim_code)
                    line.dimension_values.add(dim_value)

        entry.calculate_totals()

        # Auto-post if enabled
        if self.auto_post:
            entry.post(self.created_by)

        # Update schedule
        self.last_run_date = self.next_run_date
        self.next_run_date = self._calculate_next_run_date()
        self.save()

        return entry

    def _calculate_next_run_date(self):
        """Calculate next run date based on frequency"""
        current = self.next_run_date

        if self.frequency == 'DAILY':
            return current + timedelta(days=1)
        elif self.frequency == 'WEEKLY':
            return current + timedelta(weeks=1)
        elif self.frequency == 'BIWEEKLY':
            return current + timedelta(weeks=2)
        elif self.frequency == 'MONTHLY':
            if current.month == 12:
                return current.replace(year=current.year + 1, month=1)
            else:
                return current.replace(month=current.month + 1)
        elif self.frequency == 'QUARTERLY':
            month = current.month + 3
            year = current.year
            if month > 12:
                month -= 12
                year += 1
            return current.replace(year=year, month=month)
        elif self.frequency == 'SEMI_ANNUAL':
            month = current.month + 6
            year = current.year
            if month > 12:
                month -= 12
                year += 1
            return current.replace(year=year, month=month)
        elif self.frequency == 'ANNUAL':
            return current.replace(year=current.year + 1)

        return current


# ============================================
# BANK ACCOUNTS & TRANSACTIONS
# ============================================

class BankAccount(models.Model):
    """Bank account management"""
    account_number = models.CharField(max_length=50, unique=True)
    account_name = models.CharField(max_length=200)
    bank_name = models.CharField(max_length=200)
    bank_branch = models.CharField(max_length=200, blank=True)
    swift_code = models.CharField(max_length=20, blank=True)
    iban = models.CharField(max_length=50, blank=True)

    # GL Integration
    gl_account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.PROTECT,
        related_name='bank_accounts'
    )

    # Currency
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name='bank_accounts')

    # Balances
    opening_balance = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
    current_balance = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
    available_balance = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Balance minus holds/pending"
    )

    # Settings
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    overdraft_limit = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00')
    )

    # Bank feed integration
    enable_bank_feed = models.BooleanField(default=False)
    bank_feed_config = models.JSONField(
        null=True,
        blank=True,
        help_text="Bank feed API configuration"
    )
    last_sync_date = models.DateTimeField(null=True, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', 'bank_name', 'account_name']
        indexes = [
            models.Index(fields=['is_active', 'is_default']),
        ]

    def __str__(self):
        return f"{self.bank_name} - {self.account_number}"

    def update_balance(self):
        """Update current balance from transactions"""
        total = Transaction.objects.filter(
            bank_account=self,
            status='CLEARED'
        ).aggregate(
            deposits=Sum('amount', filter=Q(transaction_type='DEPOSIT')),
            withdrawals=Sum('amount', filter=Q(transaction_type='WITHDRAWAL'))
        )

        deposits = total['deposits'] or Decimal('0')
        withdrawals = total['withdrawals'] or Decimal('0')

        self.current_balance = self.opening_balance + deposits - withdrawals
        self.save(update_fields=['current_balance'])

    def save(self, *args, **kwargs):
        if self.is_default:
            BankAccount.objects.exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class Transaction(models.Model):
    """Bank transactions"""

    TRANSACTION_TYPES = [
        ('DEPOSIT', 'Deposit'),
        ('WITHDRAWAL', 'Withdrawal'),
        ('TRANSFER', 'Transfer'),
        ('FEE', 'Bank Fee'),
        ('INTEREST', 'Interest'),
        ('CHARGE', 'Bank Charge'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('CLEARED', 'Cleared'),
        ('RECONCILED', 'Reconciled'),
        ('CANCELLED', 'Cancelled'),
    ]

    transaction_id = models.CharField(max_length=100, unique=True, db_index=True)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name='transactions')

    # Transaction details
    transaction_date = models.DateField(db_index=True)
    value_date = models.DateField(null=True, blank=True)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)

    # Description
    description = models.CharField(max_length=500)
    reference = models.CharField(max_length=100, blank=True)
    payee = models.CharField(max_length=200, blank=True)

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    is_cleared = models.BooleanField(default=False)
    cleared_date = models.DateField(null=True, blank=True)

    # GL Integration
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bank_transactions'
    )

    # Transfer tracking
    transfer_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfer_from'
    )

    # Audit
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-transaction_date', '-created_at']
        indexes = [
            models.Index(fields=['bank_account', 'transaction_date']),
            models.Index(fields=['status', 'transaction_date']),
        ]

    def __str__(self):
        return f"{self.transaction_id} - {self.description}"

    def create_journal_entry(self, user):
        """Create journal entry for this transaction"""
        if self.journal_entry:
            raise ValidationError("Journal entry already exists")

        # Get fiscal period
        fiscal_period = FiscalPeriod.objects.filter(
            start_date__lte=self.transaction_date,
            end_date__gte=self.transaction_date,
            status='OPEN'
        ).first()

        if not fiscal_period:
            raise ValidationError(f"No open period for {self.transaction_date}")

        # Get appropriate journal
        if self.transaction_type == 'DEPOSIT':
            journal = Journal.objects.filter(journal_type=JournalType.CASH_RECEIPTS, is_active=True).first()
        else:
            journal = Journal.objects.filter(journal_type=JournalType.CASH_PAYMENTS, is_active=True).first()

        if not journal:
            journal = Journal.objects.filter(journal_type=JournalType.GENERAL, is_active=True).first()

        # Create entry
        entry = JournalEntry.objects.create(
            journal=journal,
            entry_number=journal.get_next_entry_number(),
            entry_date=self.transaction_date,
            fiscal_year=fiscal_period.fiscal_year,
            fiscal_period=fiscal_period,
            description=self.description,
            reference=self.transaction_id,
            currency=self.currency,
            created_by=user,
            source_model='finance.Transaction',
            source_id=str(self.pk)
        )

        # Create lines based on transaction type
        if self.transaction_type == 'DEPOSIT':
            # Debit: Bank account
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=self.bank_account.gl_account,
                debit_amount=self.amount,
                currency=self.currency,
                description=self.description
            )
            # Credit: (Would be specified by user - revenue, AR, etc.)
        elif self.transaction_type == 'WITHDRAWAL':
            # Credit: Bank account
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=self.bank_account.gl_account,
                credit_amount=self.amount,
                currency=self.currency,
                description=self.description
            )
            # Debit: (Would be specified by user - expense, AP, etc.)

        entry.calculate_totals()
        self.journal_entry = entry
        self.save()

        return entry

# ============================================
# ADVANCED BUDGETING
# ============================================

class BudgetType(models.TextChoices):
    ANNUAL = 'ANNUAL', _('Annual Budget')
    ROLLING = 'ROLLING', _('Rolling Forecast')
    PROJECT = 'PROJECT', _('Project Budget')
    DEPARTMENT = 'DEPARTMENT', _('Department Budget')
    ZERO_BASED = 'ZERO_BASED', _('Zero-Based Budget')


class Budget(models.Model):
    """Advanced budgeting with scenarios and forecasting"""
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True, db_index=True)
    description = models.TextField(blank=True)

    # Budget type and period
    budget_type = models.CharField(max_length=20, choices=BudgetType.choices)
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name='budgets')

    # Date range
    start_date = models.DateField()
    end_date = models.DateField()

    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('DRAFT', 'Draft'),
            ('SUBMITTED', 'Submitted'),
            ('APPROVED', 'Approved'),
            ('ACTIVE', 'Active'),
            ('CLOSED', 'Closed'),
            ('REVISED', 'Revised'),
        ],
        default='DRAFT'
    )

    # Version control
    version = models.PositiveSmallIntegerField(default=1)
    parent_budget = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='revisions'
    )

    # Scenario planning
    is_baseline = models.BooleanField(default=True)
    scenario = models.CharField(
        max_length=50,
        choices=[
            ('BASELINE', 'Baseline'),
            ('OPTIMISTIC', 'Optimistic'),
            ('PESSIMISTIC', 'Pessimistic'),
            ('WORST_CASE', 'Worst Case'),
            ('BEST_CASE', 'Best Case'),
        ],
        default='BASELINE'
    )

    # Settings
    allow_overrun = models.BooleanField(default=False)
    alert_threshold = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('90.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Alert when utilization reaches this percentage"
    )

    # Totals (cached)
    total_budget = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
    total_actual = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
    total_variance = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))

    # Audit
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='budgets_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='budgets_approved'
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-fiscal_year', 'name']
        indexes = [
            models.Index(fields=['fiscal_year', 'status']),
            models.Index(fields=['status', 'is_baseline']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def calculate_totals(self):
        """Calculate and cache totals"""
        lines = self.lines.all()
        self.total_budget = sum(line.amount for line in lines)
        self.total_actual = sum(line.get_actual_spending() for line in lines)
        self.total_variance = self.total_budget - self.total_actual
        self.save(update_fields=['total_budget', 'total_actual', 'total_variance'])

    def get_utilization(self):
        """Get overall budget utilization percentage"""
        if self.total_budget == 0:
            return Decimal('0.00')
        return (self.total_actual / self.total_budget) * 100

    def approve(self, user):
        """Approve budget"""
        if self.status != 'SUBMITTED':
            raise ValidationError("Budget must be submitted for approval")

        self.status = 'APPROVED'
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save()

    def activate(self, user):
        """Activate approved budget"""
        if self.status != 'APPROVED':
            raise ValidationError("Budget must be approved first")

        # Deactivate other active budgets for same period
        Budget.objects.filter(
            fiscal_year=self.fiscal_year,
            status='ACTIVE',
            is_baseline=self.is_baseline
        ).update(status='CLOSED')

        self.status = 'ACTIVE'
        self.save()

    def create_revision(self, user, description=''):
        """Create a new version of this budget"""
        if self.status not in ['APPROVED', 'ACTIVE']:
            raise ValidationError("Can only revise approved/active budgets")

        new_version = Budget.objects.create(
            name=f"{self.name} (Rev {self.version + 1})",
            code=f"{self.code}-R{self.version + 1}",
            description=description or self.description,
            budget_type=self.budget_type,
            fiscal_year=self.fiscal_year,
            start_date=self.start_date,
            end_date=self.end_date,
            status='DRAFT',
            version=self.version + 1,
            parent_budget=self,
            is_baseline=self.is_baseline,
            scenario=self.scenario,
            created_by=user
        )

        # Copy budget lines
        for line in self.lines.all():
            BudgetLine.objects.create(
                budget=new_version,
                account=line.account,
                amount=line.amount,
                description=line.description,
                period_distribution=line.period_distribution
            )

            # Copy dimensions
            for dim in line.dimension_values.all():
                new_version.lines.last().dimension_values.add(dim)

        self.status = 'REVISED'
        self.save()

        return new_version


class BudgetLine(models.Model):
    """Budget line items with period distribution"""
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='lines')
    account = models.ForeignKey(ChartOfAccounts, on_delete=models.PROTECT, related_name='budget_lines')

    # Dimensions
    dimension_values = models.ManyToManyField(DimensionValue, blank=True, related_name='budget_lines')

    # Amounts
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, default=1)

    # Period distribution (for monthly/quarterly breakdown)
    period_distribution = models.JSONField(
        default=dict,
        help_text="JSON with period-wise distribution: {period_id: amount}"
    )

    # Notes
    description = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)

    # Cached actuals
    actual_amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00')
    )
    last_actual_update = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['budget', 'account__code']
        indexes = [
            models.Index(fields=['budget', 'account']),
        ]

    def __str__(self):
        return f"{self.budget.code} - {self.account.code}"

    def get_actual_spending(self):
        """Get actual spending against this budget line"""
        filters = Q(
            account=self.account,
            journal_entry__status='POSTED',
            journal_entry__posting_date__range=[
                self.budget.start_date,
                self.budget.end_date
            ]
        )

        # Filter by dimensions if specified
        for dim_value in self.dimension_values.all():
            filters &= Q(dimension_values=dim_value)

        lines = JournalEntryLine.objects.filter(filters)

        if self.account.is_debit_account:
            total = lines.aggregate(
                total=Sum('debit_amount') - Sum('credit_amount')
            )['total']
        else:
            total = lines.aggregate(
                total=Sum('credit_amount') - Sum('debit_amount')
            )['total']

        return total or Decimal('0.00')

    def get_variance(self):
        """Get variance (budget - actual)"""
        actual = self.get_actual_spending()
        return self.amount - actual

    def get_utilization_percentage(self):
        """Get utilization as percentage"""
        if self.amount == 0:
            return Decimal('0.00')
        actual = self.get_actual_spending()
        return (actual / self.amount) * 100

    def update_actual(self):
        """Update cached actual amount"""
        self.actual_amount = self.get_actual_spending()
        self.last_actual_update = timezone.now()
        self.save(update_fields=['actual_amount', 'last_actual_update'])


# ============================================
# TAX MANAGEMENT
# ============================================

class TaxCode(models.Model):
    """Tax codes for sales/purchase tax"""
    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    # Tax settings
    tax_type = models.CharField(
        max_length=20,
        choices=[
            ('SALES', 'Sales Tax'),
            ('PURCHASE', 'Purchase Tax'),
            ('VAT', 'Value Added Tax'),
            ('GST', 'Goods and Services Tax'),
            ('WITHHOLDING', 'Withholding Tax'),
            ('EXCISE', 'Excise Tax'),
            ('CUSTOM', 'Custom Duty'),
        ]
    )
    rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Tax rate as percentage"
    )

    # GL Accounts
    tax_collected_account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.PROTECT,
        related_name='tax_collected_codes',
        help_text="Account for tax collected (liability)"
    )
    tax_paid_account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.PROTECT,
        related_name='tax_paid_codes',
        help_text="Account for tax paid (asset)"
    )

    # Settings
    is_compound = models.BooleanField(
        default=False,
        help_text="Tax calculated on tax-inclusive amount"
    )
    is_active = models.BooleanField(default=True)
    effective_date = models.DateField(default=timezone.now)
    expiry_date = models.DateField(null=True, blank=True)

    # Reporting
    tax_authority = models.CharField(max_length=200, blank=True)
    filing_frequency = models.CharField(
        max_length=20,
        choices=[
            ('MONTHLY', 'Monthly'),
            ('QUARTERLY', 'Quarterly'),
            ('ANNUAL', 'Annual'),
        ],
        default='MONTHLY'
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name} ({self.rate}%)"

    def calculate_tax(self, amount, is_tax_inclusive=False):
        """Calculate tax amount"""
        if is_tax_inclusive:
            # Extract tax from inclusive amount
            return amount - (amount / (1 + (self.rate / 100)))
        else:
            # Calculate tax on exclusive amount
            return amount * (self.rate / 100)


# ============================================
# FIXED ASSETS
# ============================================

class AssetCategory(models.Model):
    """Fixed asset categories"""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    # GL Accounts
    asset_account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.PROTECT,
        related_name='asset_categories_asset'
    )
    accumulated_depreciation_account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.PROTECT,
        related_name='asset_categories_depreciation'
    )
    depreciation_expense_account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.PROTECT,
        related_name='asset_categories_expense'
    )
    gain_loss_account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.PROTECT,
        related_name='asset_categories_gain_loss'
    )

    # Depreciation defaults
    default_depreciation_method = models.CharField(
        max_length=20,
        choices=[
            ('STRAIGHT_LINE', 'Straight Line'),
            ('DECLINING_BALANCE', 'Declining Balance'),
            ('DOUBLE_DECLINING', 'Double Declining Balance'),
            ('SUM_OF_YEARS', 'Sum of Years Digits'),
            ('UNITS_OF_PRODUCTION', 'Units of Production'),
        ],
        default='STRAIGHT_LINE'
    )
    default_useful_life_years = models.PositiveSmallIntegerField(default=5)
    default_salvage_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Asset Categories"
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"


class FixedAsset(models.Model):
    """Fixed assets with depreciation"""

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('ACTIVE', 'Active'),
        ('DISPOSED', 'Disposed'),
        ('RETIRED', 'Retired'),
        ('SOLD', 'Sold'),
        ('LOST', 'Lost/Stolen'),
    ]

    asset_number = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT, related_name='assets')

    # Purchase details
    purchase_date = models.DateField()
    purchase_cost = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name='fixed_assets')
    vendor = models.CharField(max_length=200, blank=True)
    invoice_number = models.CharField(max_length=100, blank=True)

    # Location and assignment
    location = models.CharField(max_length=200, blank=True)
    dimension_values = models.ManyToManyField(DimensionValue, blank=True, related_name='fixed_assets')
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_assets'
    )

    # Depreciation settings
    depreciation_method = models.CharField(
        max_length=20,
        choices=[
            ('STRAIGHT_LINE', 'Straight Line'),
            ('DECLINING_BALANCE', 'Declining Balance'),
            ('DOUBLE_DECLINING', 'Double Declining Balance'),
            ('SUM_OF_YEARS', 'Sum of Years Digits'),
            ('UNITS_OF_PRODUCTION', 'Units of Production'),
        ]
    )
    useful_life_years = models.PositiveSmallIntegerField()
    useful_life_months = models.PositiveSmallIntegerField(default=0)
    salvage_value = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00')
    )
    depreciation_start_date = models.DateField()

    # For units of production method
    total_units = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Total expected units for production-based depreciation"
    )
    units_produced_to_date = models.PositiveIntegerField(default=0)

    # Calculated values
    depreciable_amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00')
    )
    accumulated_depreciation = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00')
    )
    book_value = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00')
    )

    # Disposal details
    disposal_date = models.DateField(null=True, blank=True)
    disposal_proceeds = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True
    )
    disposal_gain_loss = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True
    )

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')

    # Audit
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='assets_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fixed Asset"
        ordering = ['asset_number']
        indexes = [
            models.Index(fields=['status', 'category']),
            models.Index(fields=['depreciation_start_date']),
        ]

    def __str__(self):
        return f"{self.asset_number} - {self.name}"

    def save(self, *args, **kwargs):
        # Calculate depreciable amount
        self.depreciable_amount = self.purchase_cost - self.salvage_value

        # Calculate book value
        self.book_value = self.purchase_cost - self.accumulated_depreciation

        super().save(*args, **kwargs)

    def calculate_depreciation(self, as_of_date=None):
        """Calculate depreciation for a period"""
        if not as_of_date:
            as_of_date = timezone.now().date()

        if as_of_date < self.depreciation_start_date:
            return Decimal('0.00')

        if self.depreciation_method == 'STRAIGHT_LINE':
            return self._calculate_straight_line(as_of_date)
        elif self.depreciation_method == 'DECLINING_BALANCE':
            return self._calculate_declining_balance(as_of_date)
        elif self.depreciation_method == 'DOUBLE_DECLINING':
            return self._calculate_double_declining(as_of_date)
        elif self.depreciation_method == 'SUM_OF_YEARS':
            return self._calculate_sum_of_years(as_of_date)
        elif self.depreciation_method == 'UNITS_OF_PRODUCTION':
            return self._calculate_units_of_production()

        return Decimal('0.00')

    def _calculate_straight_line(self, as_of_date):
        """Straight line depreciation"""
        total_months = (self.useful_life_years * 12) + self.useful_life_months
        if total_months == 0:
            return Decimal('0.00')

        monthly_depreciation = self.depreciable_amount / total_months
        return monthly_depreciation

    def _calculate_declining_balance(self, as_of_date, factor=1.5):
        """Declining balance depreciation"""
        rate = factor / self.useful_life_years
        remaining_value = self.purchase_cost - self.accumulated_depreciation
        annual_depreciation = remaining_value * Decimal(str(rate))

        # Don't depreciate below salvage value
        if remaining_value - annual_depreciation < self.salvage_value:
            annual_depreciation = remaining_value - self.salvage_value

        return annual_depreciation / 12

    def _calculate_double_declining(self, as_of_date):
        """Double declining balance"""
        return self._calculate_declining_balance(as_of_date, factor=2.0)

    def _calculate_sum_of_years(self, as_of_date):
        """Sum of years digits depreciation"""
        total_years = self.useful_life_years
        sum_of_years = (total_years * (total_years + 1)) / 2

        # Calculate which year we're in
        months_elapsed = (as_of_date.year - self.depreciation_start_date.year) * 12
        months_elapsed += (as_of_date.month - self.depreciation_start_date.month)
        years_elapsed = months_elapsed // 12

        remaining_years = total_years - years_elapsed
        if remaining_years <= 0:
            return Decimal('0.00')

        annual_depreciation = (Decimal(str(remaining_years)) / Decimal(str(sum_of_years))) * self.depreciable_amount
        return annual_depreciation / 12

    def _calculate_units_of_production(self):
        """Units of production depreciation"""
        if not self.total_units or self.total_units == 0:
            return Decimal('0.00')

        per_unit_depreciation = self.depreciable_amount / self.total_units
        # This would be called when units are produced
        return per_unit_depreciation

    def record_depreciation(self, amount, for_period, user):
        """Record depreciation entry"""
        if self.status != 'ACTIVE':
            raise ValidationError("Asset must be active to record depreciation")

        # Check if already depreciated for this period
        if self.depreciation_records.filter(fiscal_period=for_period).exists():
            raise ValidationError(f"Depreciation already recorded for {for_period.name}")

        # Get journal
        journal = Journal.objects.filter(
            journal_type=JournalType.DEPRECIATION,
            is_active=True
        ).first()

        if not journal:
            journal = Journal.objects.filter(
                journal_type=JournalType.GENERAL,
                is_active=True
            ).first()

        # Create journal entry
        entry = JournalEntry.objects.create(
            journal=journal,
            entry_number=journal.get_next_entry_number(),
            entry_date=for_period.end_date,
            fiscal_year=for_period.fiscal_year,
            fiscal_period=for_period,
            description=f"Depreciation - {self.name}",
            reference=self.asset_number,
            currency=self.currency,
            created_by=user,
            source_model='finance.FixedAsset',
            source_id=str(self.pk)
        )

        # Debit: Depreciation Expense
        JournalEntryLine.objects.create(
            journal_entry=entry,
            account=self.category.depreciation_expense_account,
            debit_amount=amount,
            currency=self.currency,
            description=f"Depreciation - {self.name}"
        )

        # Credit: Accumulated Depreciation
        JournalEntryLine.objects.create(
            journal_entry=entry,
            account=self.category.accumulated_depreciation_account,
            credit_amount=amount,
            currency=self.currency,
            description=f"Accumulated depreciation - {self.name}"
        )

        # Add dimensions
        for dim_value in self.dimension_values.all():
            for line in entry.lines.all():
                line.dimension_values.add(dim_value)

        entry.calculate_totals()
        entry.post(user)

        # Create depreciation record
        depreciation_record = DepreciationRecord.objects.create(
            asset=self,
            fiscal_period=for_period,
            depreciation_amount=amount,
            accumulated_depreciation=self.accumulated_depreciation + amount,
            book_value=self.book_value - amount,
            journal_entry=entry,
            created_by=user
        )

        # Update asset
        self.accumulated_depreciation += amount
        self.book_value -= amount
        self.save()

        return depreciation_record

    def dispose(self, disposal_date, proceeds, user):
        """Dispose of asset"""
        if self.status == 'DISPOSED':
            raise ValidationError("Asset already disposed")

        # Calculate final depreciation up to disposal date
        # (This would be more complex in real implementation)

        # Calculate gain/loss
        gain_loss = proceeds - self.book_value

        # Create disposal journal entry
        fiscal_period = FiscalPeriod.objects.filter(
            start_date__lte=disposal_date,
            end_date__gte=disposal_date,
            status='OPEN'
        ).first()

        if not fiscal_period:
            raise ValidationError(f"No open period for {disposal_date}")

        journal = Journal.objects.filter(
            journal_type=JournalType.GENERAL,
            is_active=True
        ).first()

        entry = JournalEntry.objects.create(
            journal=journal,
            entry_number=journal.get_next_entry_number(),
            entry_date=disposal_date,
            fiscal_year=fiscal_period.fiscal_year,
            fiscal_period=fiscal_period,
            description=f"Disposal of {self.name}",
            reference=self.asset_number,
            currency=self.currency,
            created_by=user
        )

        # Debit: Cash/Bank (proceeds)
        if proceeds > 0:
            # This would reference a specific bank account
            pass

        # Debit: Accumulated Depreciation
        JournalEntryLine.objects.create(
            journal_entry=entry,
            account=self.category.accumulated_depreciation_account,
            debit_amount=self.accumulated_depreciation,
            currency=self.currency,
            description=f"Remove accumulated depreciation - {self.name}"
        )

        # Credit: Asset Account
        JournalEntryLine.objects.create(
            journal_entry=entry,
            account=self.category.asset_account,
            credit_amount=self.purchase_cost,
            currency=self.currency,
            description=f"Remove asset - {self.name}"
        )

        # Gain or Loss
        if gain_loss != 0:
            if gain_loss > 0:
                # Credit: Gain on disposal
                JournalEntryLine.objects.create(
                    journal_entry=entry,
                    account=self.category.gain_loss_account,
                    credit_amount=abs(gain_loss),
                    currency=self.currency,
                    description=f"Gain on disposal - {self.name}"
                )
            else:
                # Debit: Loss on disposal
                JournalEntryLine.objects.create(
                    journal_entry=entry,
                    account=self.category.gain_loss_account,
                    debit_amount=abs(gain_loss),
                    currency=self.currency,
                    description=f"Loss on disposal - {self.name}"
                )

        entry.calculate_totals()
        entry.post(user)

        # Update asset
        self.status = 'DISPOSED'
        self.disposal_date = disposal_date
        self.disposal_proceeds = proceeds
        self.disposal_gain_loss = gain_loss
        self.save()


class DepreciationRecord(models.Model):
    """Track depreciation history"""
    asset = models.ForeignKey(FixedAsset, on_delete=models.CASCADE, related_name='depreciation_records')
    fiscal_period = models.ForeignKey(FiscalPeriod, on_delete=models.PROTECT, related_name='depreciation_records')

    depreciation_amount = models.DecimalField(max_digits=20, decimal_places=2)
    accumulated_depreciation = models.DecimalField(max_digits=20, decimal_places=2)
    book_value = models.DecimalField(max_digits=20, decimal_places=2)

    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        related_name='depreciation_records'
    )

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['asset', 'fiscal_period']
        ordering = ['-fiscal_period__start_date']

    def __str__(self):
        return f"{self.asset.asset_number} - {self.fiscal_period.name}"


# ============================================
# BANK RECONCILIATION
# ============================================

class BankReconciliation(models.Model):
    """Bank reconciliation management"""

    STATUS_CHOICES = [
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('APPROVED', 'Approved'),
    ]

    reconciliation_number = models.CharField(max_length=50, unique=True, db_index=True)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name='reconciliations')

    # Period
    reconciliation_date = models.DateField()
    start_date = models.DateField()
    end_date = models.DateField()

    # Balances
    opening_balance = models.DecimalField(max_digits=20, decimal_places=2)
    closing_balance_book = models.DecimalField(max_digits=20, decimal_places=2)
    closing_balance_bank = models.DecimalField(max_digits=20, decimal_places=2)

    # Calculated
    total_deposits_in_transit = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00')
    )
    total_outstanding_checks = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00')
    )
    total_adjustments = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00')
    )
    difference = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('0.00')
    )

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='IN_PROGRESS')
    is_balanced = models.BooleanField(default=False)

    # Notes
    notes = models.TextField(blank=True)

    # Audit
    reconciled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='reconciliations_performed'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reconciliations_approved'
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-reconciliation_date']
        indexes = [
            models.Index(fields=['bank_account', 'reconciliation_date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.reconciliation_number} - {self.bank_account.account_number}"

    def calculate_balance(self):
        """Calculate reconciled balance"""
        # Start with bank statement balance
        calculated = self.closing_balance_bank

        # Add deposits in transit
        calculated += self.total_deposits_in_transit

        # Subtract outstanding checks
        calculated -= self.total_outstanding_checks

        # Add/subtract adjustments
        calculated += self.total_adjustments

        # Calculate difference
        self.difference = calculated - self.closing_balance_book
        self.is_balanced = abs(self.difference) < Decimal('0.01')

        self.save()

    def complete(self):
        """Complete reconciliation"""
        if self.status == 'COMPLETED':
            raise ValidationError("Reconciliation already completed")

        if not self.is_balanced:
            raise ValidationError("Reconciliation is not balanced")

        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        self.save()

        # Mark matched transactions as reconciled
        self.items.filter(is_matched=True).update(is_reconciled=True)


class BankReconciliationItem(models.Model):
    """Individual reconciliation items"""

    ITEM_TYPE_CHOICES = [
        ('DEPOSIT_IN_TRANSIT', 'Deposit in Transit'),
        ('OUTSTANDING_CHECK', 'Outstanding Check'),
        ('BANK_ERROR', 'Bank Error'),
        ('BOOK_ERROR', 'Book Error'),
        ('ADJUSTMENT', 'Adjustment'),
    ]

    reconciliation = models.ForeignKey(
        BankReconciliation,
        on_delete=models.CASCADE,
        related_name='items'
    )

    item_type = models.CharField(max_length=30, choices=ITEM_TYPE_CHOICES)
    transaction_date = models.DateField()
    description = models.CharField(max_length=500)
    amount = models.DecimalField(max_digits=20, decimal_places=2)

    # Matching
    book_transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reconciliation_items'
    )
    is_matched = models.BooleanField(default=False)
    is_reconciled = models.BooleanField(default=False)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['transaction_date']

    def __str__(self):
        return f"{self.reconciliation.reconciliation_number} - {self.description}"


class BankStatement(models.Model):
    """Bank statement imports"""
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name='statements')

    statement_date = models.DateField()
    opening_balance = models.DecimalField(max_digits=20, decimal_places=2)
    closing_balance = models.DecimalField(max_digits=20, decimal_places=2)

    # File details
    file_name = models.CharField(max_length=255)
    file_format = models.CharField(
        max_length=20,
        choices=[
            ('CSV', 'CSV'),
            ('OFX', 'OFX'),
            ('QIF', 'QIF'),
            ('MT940', 'MT940'),
            ('BAI2', 'BAI2'),
        ]
    )

    # Processing
    is_processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    transactions_imported = models.PositiveIntegerField(default=0)

    # Audit
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-statement_date']
        indexes = [
            models.Index(fields=['bank_account', 'statement_date']),
        ]

    def __str__(self):
        return f"{self.bank_account.account_number} - {self.statement_date}"


class BankTransaction(models.Model):
    """Transactions from bank statements"""
    bank_statement = models.ForeignKey(
        BankStatement,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name='bank_transactions')

    transaction_date = models.DateField()
    value_date = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=500)
    reference = models.CharField(max_length=100, blank=True)

    amount = models.DecimalField(max_digits=20, decimal_places=2)
    balance = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)

    transaction_type = models.CharField(
        max_length=20,
        choices=[
            ('DEPOSIT', 'Deposit'),
            ('WITHDRAWAL', 'Withdrawal'),
            ('FEE', 'Fee'),
            ('INTEREST', 'Interest'),
        ]
    )

    # Matching
    matched_transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bank_statement_match'
    )
    is_reconciled = models.BooleanField(default=False)
    reconciliation = models.ForeignKey(
        BankReconciliation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bank_transactions'
    )

    # Import tracking
    import_batch = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['bank_account', 'transaction_date']),
            models.Index(fields=['is_reconciled']),
        ]

    def __str__(self):
        return f"{self.bank_account.account_number} - {self.description}"


# ============================================
# FINANCIAL REPORTING
# ============================================

class FinancialReport(models.Model):
    """Generated financial reports"""

    REPORT_TYPES = [
        ('BALANCE_SHEET', 'Balance Sheet'),
        ('INCOME_STATEMENT', 'Income Statement'),
        ('CASH_FLOW', 'Cash Flow Statement'),
        ('TRIAL_BALANCE', 'Trial Balance'),
        ('GENERAL_LEDGER', 'General Ledger'),
        ('AGED_RECEIVABLES', 'Aged Receivables'),
        ('AGED_PAYABLES', 'Aged Payables'),
        ('BUDGET_VARIANCE', 'Budget Variance'),
        ('CUSTOM', 'Custom Report'),
    ]

    name = models.CharField(max_length=200)
    report_type = models.CharField(max_length=30, choices=REPORT_TYPES)
    description = models.TextField(blank=True)

    # Period
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    as_of_date = models.DateField(null=True, blank=True)
    fiscal_period = models.ForeignKey(
        FiscalPeriod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Report data
    report_data = models.JSONField(help_text="Generated report data in JSON")

    # Filters
    filters_applied = models.JSONField(
        default=dict,
        help_text="Dimensions and other filters applied"
    )

    # Status
    is_final = models.BooleanField(default=False)

    # Audit
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['report_type', '-generated_at']),
        ]

    def __str__(self):
        return f"{self.get_report_type_display()} - {self.generated_at.date()}"


# ============================================
# AUDIT TRAIL
# ============================================

class AuditLog(models.Model):
    """Comprehensive audit trail"""

    ACTION_CHOICES = [
        ('CREATE', 'Created'),
        ('UPDATE', 'Updated'),
        ('DELETE', 'Deleted'),
        ('POST', 'Posted'),
        ('APPROVE', 'Approved'),
        ('REVERSE', 'Reversed'),
        ('CLOSE', 'Closed'),
        ('LOCK', 'Locked'),
    ]

    # What was changed
    model_name = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=100, db_index=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)

    # Changes detail
    field_name = models.CharField(max_length=100, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    changes_json = models.JSONField(
        null=True,
        blank=True,
        help_text="Complete change set in JSON"
    )

    # Context
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)

    # Audit
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='audit_logs')
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['model_name', 'object_id']),
            models.Index(fields=['-timestamp']),
            models.Index(fields=['user', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.user} {self.action} {self.model_name} {self.object_id}"