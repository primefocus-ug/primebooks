from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Sum, Q, F
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
import uuid
import json


class ExpenseCategory(models.Model):
    """Hierarchical expense categories"""

    CATEGORY_TYPES = [
        ('OPERATIONAL', _('Operational Expenses')),
        ('ADMINISTRATIVE', _('Administrative Expenses')),
        ('MARKETING', _('Marketing & Advertising')),
        ('UTILITIES', _('Utilities')),
        ('INVENTORY', _('Inventory & Supplies')),
        ('PAYROLL', _('Payroll & Benefits')),
        ('MAINTENANCE', _('Maintenance & Repairs')),
        ('PROFESSIONAL', _('Professional Services')),
        ('TRAVEL', _('Travel & Entertainment')),
        ('OTHER', _('Other Expenses')),
    ]

    name = models.CharField(
        max_length=100,
        verbose_name=_("Category Name")
    )
    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_("Category Code"),
        help_text=_("Unique identifier for accounting")
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subcategories',
        verbose_name=_("Parent Category")
    )
    category_type = models.CharField(
        max_length=20,
        choices=CATEGORY_TYPES,
        default='OTHER',
        verbose_name=_("Category Type")
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Description")
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )
    requires_approval = models.BooleanField(
        default=True,
        verbose_name=_("Requires Approval"),
        help_text=_("Whether expenses in this category need approval")
    )
    approval_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Auto-Approval Limit"),
        help_text=_("Expenses below this amount are auto-approved")
    )
    is_taxable = models.BooleanField(
        default=True,
        verbose_name=_("Taxable"),
        help_text=_("Whether expenses in this category include VAT")
    )
    default_tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=18.00,
        verbose_name=_("Default Tax Rate %")
    )
    budget_allocation = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Budget Allocation"),
        help_text=_("Default budget for this category")
    )
    color_code = models.CharField(
        max_length=7,
        default='#6c757d',
        verbose_name=_("Color Code"),
        help_text=_("Hex color for visualization")
    )
    icon = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Icon Class"),
        help_text=_("CSS icon class (e.g., fa-shopping-cart)")
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Sort Order")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Expense Category")
        verbose_name_plural = _("Expense Categories")
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['category_type', 'is_active']),
            models.Index(fields=['parent']),
        ]

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} > {self.name}"
        return self.name

    def get_full_path(self):
        """Get full category path"""
        path = [self.name]
        parent = self.parent
        while parent:
            path.insert(0, parent.name)
            parent = parent.parent
        return " > ".join(path)

    def get_all_subcategories(self):
        """Get all subcategories recursively"""
        subcats = list(self.subcategories.all())
        for subcat in list(subcats):
            subcats.extend(subcat.get_all_subcategories())
        return subcats

    def total_expenses(self, start_date=None, end_date=None):
        """Calculate total expenses for this category"""
        query = Q(category=self)

        # Include subcategories
        subcats = self.get_all_subcategories()
        if subcats:
            query |= Q(category__in=subcats)

        expenses = Expense.objects.filter(query, status='PAID')

        if start_date:
            expenses = expenses.filter(expense_date__gte=start_date)
        if end_date:
            expenses = expenses.filter(expense_date__lte=end_date)

        result = expenses.aggregate(total=Sum('total_amount'))
        return result['total'] or Decimal('0.00')


class Vendor(models.Model):
    """Vendor/Supplier management"""

    VENDOR_TYPES = [
        ('SUPPLIER', _('Supplier')),
        ('SERVICE_PROVIDER', _('Service Provider')),
        ('CONTRACTOR', _('Contractor')),
        ('UTILITY', _('Utility Company')),
        ('LANDLORD', _('Landlord')),
        ('OTHER', _('Other')),
    ]

    PAYMENT_TERMS = [
        ('IMMEDIATE', _('Immediate Payment')),
        ('NET_7', _('Net 7 Days')),
        ('NET_15', _('Net 15 Days')),
        ('NET_30', _('Net 30 Days')),
        ('NET_60', _('Net 60 Days')),
        ('NET_90', _('Net 90 Days')),
        ('CUSTOM', _('Custom Terms')),
    ]

    vendor_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )
    name = models.CharField(
        max_length=200,
        verbose_name=_("Vendor Name")
    )
    vendor_type = models.CharField(
        max_length=20,
        choices=VENDOR_TYPES,
        default='SUPPLIER',
        verbose_name=_("Vendor Type")
    )
    contact_person = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Contact Person")
    )
    email = models.EmailField(
        blank=True,
        verbose_name=_("Email")
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Phone Number")
    )
    address = models.TextField(
        blank=True,
        verbose_name=_("Address")
    )

    # Tax Information
    tin = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("TIN"),
        help_text=_("Tax Identification Number")
    )
    is_registered_for_vat = models.BooleanField(
        default=False,
        verbose_name=_("VAT Registered")
    )

    # Payment Terms
    payment_terms = models.CharField(
        max_length=20,
        choices=PAYMENT_TERMS,
        default='NET_30',
        verbose_name=_("Payment Terms")
    )
    custom_payment_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Custom Payment Days")
    )
    credit_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Credit Limit")
    )

    # Banking Details
    bank_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Bank Name")
    )
    account_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Account Number")
    )
    account_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Account Name")
    )
    mobile_money_number = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Mobile Money Number")
    )

    # Status & Rating
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )
    is_approved = models.BooleanField(
        default=False,
        verbose_name=_("Approved Vendor")
    )
    rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        verbose_name=_("Rating (0-5)")
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_vendors'
    )

    class Meta:
        verbose_name = _("Vendor")
        verbose_name_plural = _("Vendors")
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['vendor_type', 'is_active']),
            models.Index(fields=['tin']),
        ]

    def __str__(self):
        return self.name

    @property
    def total_spent(self):
        """Total amount spent with this vendor"""
        result = self.expenses.filter(
            status='PAID'
        ).aggregate(total=Sum('total_amount'))
        return result['total'] or Decimal('0.00')

    @property
    def outstanding_balance(self):
        """Total outstanding balance"""
        result = self.expenses.filter(
            status__in=['APPROVED', 'PARTIALLY_PAID']
        ).aggregate(total=Sum('amount_due'))
        return result['total'] or Decimal('0.00')

    @property
    def payment_term_days(self):
        """Get payment term in days"""
        if self.payment_terms == 'CUSTOM':
            return self.custom_payment_days or 30

        terms_mapping = {
            'IMMEDIATE': 0,
            'NET_7': 7,
            'NET_15': 15,
            'NET_30': 30,
            'NET_60': 60,
            'NET_90': 90,
        }
        return terms_mapping.get(self.payment_terms, 30)

    def within_credit_limit(self, amount):
        """Check if new expense would exceed credit limit"""
        if not self.credit_limit:
            return True
        total_outstanding = self.outstanding_balance + Decimal(amount)
        return total_outstanding <= self.credit_limit


class Budget(models.Model):
    """Budget management per category/store/period"""

    BUDGET_PERIODS = [
        ('MONTHLY', _('Monthly')),
        ('QUARTERLY', _('Quarterly')),
        ('YEARLY', _('Yearly')),
        ('CUSTOM', _('Custom Period')),
    ]

    name = models.CharField(
        max_length=100,
        verbose_name=_("Budget Name")
    )
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.CASCADE,
        related_name='budgets',
        verbose_name=_("Category")
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='budgets',
        verbose_name=_("Store"),
        help_text=_("Leave blank for company-wide budget")
    )
    budget_period = models.CharField(
        max_length=20,
        choices=BUDGET_PERIODS,
        default='MONTHLY',
        verbose_name=_("Budget Period")
    )
    start_date = models.DateField(
        verbose_name=_("Start Date")
    )
    end_date = models.DateField(
        verbose_name=_("End Date")
    )
    allocated_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Allocated Amount")
    )

    # Alert Thresholds
    warning_threshold = models.PositiveIntegerField(
        default=80,
        validators=[MaxValueValidator(100)],
        verbose_name=_("Warning Threshold %"),
        help_text=_("Alert when budget reaches this percentage")
    )
    critical_threshold = models.PositiveIntegerField(
        default=95,
        validators=[MaxValueValidator(100)],
        verbose_name=_("Critical Threshold %")
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_budgets'
    )

    class Meta:
        verbose_name = _("Budget")
        verbose_name_plural = _("Budgets")
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['category', 'start_date', 'end_date']),
            models.Index(fields=['store', 'is_active']),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(end_date__gte=F('start_date')),
                name='valid_budget_period'
            )
        ]

    def __str__(self):
        store_str = f" - {self.store.name}" if self.store else ""
        return f"{self.name} ({self.category.name}){store_str}"

    @property
    def spent_amount(self):
        """Calculate total spent against this budget"""
        expenses = Expense.objects.filter(
            category=self.category,
            expense_date__gte=self.start_date,
            expense_date__lte=self.end_date,
            status='PAID'
        )

        if self.store:
            expenses = expenses.filter(store=self.store)

        result = expenses.aggregate(total=Sum('total_amount'))
        return result['total'] or Decimal('0.00')

    @property
    def remaining_amount(self):
        """Calculate remaining budget"""
        return self.allocated_amount - self.spent_amount

    @property
    def utilization_percentage(self):
        """Calculate budget utilization percentage"""
        if self.allocated_amount == 0:
            return 0
        return (self.spent_amount / self.allocated_amount * 100).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

    @property
    def status(self):
        """Get budget status based on utilization"""
        utilization = self.utilization_percentage

        if utilization >= self.critical_threshold:
            return 'CRITICAL'
        elif utilization >= self.warning_threshold:
            return 'WARNING'
        elif utilization >= 100:
            return 'EXCEEDED'
        else:
            return 'NORMAL'

    def is_exceeded(self):
        """Check if budget is exceeded"""
        return self.spent_amount > self.allocated_amount


class Expense(models.Model):
    """Main expense/expenditure model"""

    EXPENSE_TYPES = [
        ('PURCHASE', _('Purchase')),
        ('SERVICE', _('Service Payment')),
        ('UTILITY', _('Utility Bill')),
        ('RENT', _('Rent Payment')),
        ('SALARY', _('Salary/Wages')),
        ('MAINTENANCE', _('Maintenance')),
        ('TRAVEL', _('Travel Expense')),
        ('ENTERTAINMENT', _('Entertainment')),
        ('ADVERTISING', _('Advertising')),
        ('INSURANCE', _('Insurance')),
        ('TAX', _('Tax Payment')),
        ('LOAN', _('Loan Payment')),
        ('PETTY_CASH', _('Petty Cash')),
        ('REIMBURSEMENT', _('Employee Reimbursement')),
        ('OTHER', _('Other')),
    ]

    STATUS_CHOICES = [
        ('DRAFT', _('Draft')),
        ('PENDING', _('Pending Approval')),
        ('APPROVED', _('Approved')),
        ('REJECTED', _('Rejected')),
        ('PAID', _('Paid')),
        ('PARTIALLY_PAID', _('Partially Paid')),
        ('CANCELLED', _('Cancelled')),
    ]

    PAYMENT_METHODS = [
        ('CASH', _('Cash')),
        ('BANK_TRANSFER', _('Bank Transfer')),
        ('MOBILE_MONEY', _('Mobile Money')),
        ('CHEQUE', _('Cheque')),
        ('CREDIT_CARD', _('Credit Card')),
        ('PETTY_CASH', _('Petty Cash')),
        ('OTHER', _('Other')),
    ]

    # Core Fields
    expense_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )
    expense_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name=_("Expense Number")
    )

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.PROTECT,
        related_name='expenses',
        verbose_name=_("Store")
    )
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,
        related_name='expenses',
        verbose_name=_("Category")
    )
    expense_type = models.CharField(
        max_length=20,
        choices=EXPENSE_TYPES,
        default='OTHER',
        verbose_name=_("Expense Type")
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expenses',
        verbose_name=_("Vendor")
    )

    # Financial Details
    description = models.TextField(
        verbose_name=_("Description")
    )
    expense_date = models.DateField(
        default=timezone.now,
        verbose_name=_("Expense Date")
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Amount")
    )
    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Tax Amount (VAT)")
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=18.00,
        verbose_name=_("Tax Rate %")
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Total Amount")
    )
    currency = models.CharField(
        max_length=3,
        default='UGX',
        verbose_name=_("Currency")
    )

    # Payment Information
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT',
        db_index=True,
        verbose_name=_("Status")
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHODS,
        blank=True,
        verbose_name=_("Payment Method")
    )
    payment_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Payment Date")
    )
    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Payment Reference"),
        help_text=_("Transaction ID, cheque number, etc.")
    )
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Amount Paid")
    )

    # Due Date & Recurring
    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Due Date")
    )
    is_recurring = models.BooleanField(
        default=False,
        verbose_name=_("Recurring Expense")
    )
    recurring_schedule = models.ForeignKey(
        'RecurringExpense',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_expenses'
    )

    # Approval Workflow
    requires_approval = models.BooleanField(
        default=True,
        verbose_name=_("Requires Approval")
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_expenses',
        verbose_name=_("Approved By")
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Approved At")
    )
    rejection_reason = models.TextField(
        blank=True,
        verbose_name=_("Rejection Reason")
    )

    # References
    invoice_number = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Invoice/Receipt Number")
    )
    purchase_order = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Purchase Order Number")
    )

    # Split Expense
    is_split = models.BooleanField(
        default=False,
        verbose_name=_("Split Expense"),
        help_text=_("Expense allocated across multiple stores/departments")
    )

    # EFRIS Integration
    is_efris_compliant = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Compliant"),
        help_text=_("Has valid EFRIS invoice from vendor")
    )
    efris_invoice_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("EFRIS Invoice Number")
    )
    efris_verification_code = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("EFRIS Verification Code")
    )
    can_claim_input_tax = models.BooleanField(
        default=False,
        verbose_name=_("Can Claim Input Tax"),
        help_text=_("Eligible for VAT input tax credit")
    )

    # Tracking
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_expenses',
        verbose_name=_("Created By")
    )
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paid_expenses',
        verbose_name=_("Paid By")
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Expense")
        verbose_name_plural = _("Expenses")
        ordering = ['-expense_date', '-created_at']
        indexes = [
            models.Index(fields=['expense_number']),
            models.Index(fields=['store', 'expense_date']),
            models.Index(fields=['category', 'status']),
            models.Index(fields=['vendor', 'status']),
            models.Index(fields=['status', 'expense_date']),
            models.Index(fields=['created_by', '-created_at']),
        ]
        permissions = [
            ('approve_expense', 'Can approve expenses'),
            ('reject_expense', 'Can reject expenses'),
            ('pay_expense', 'Can mark expenses as paid'),
            ('view_all_expenses', 'Can view all company expenses'),
        ]

    def __str__(self):
        return f"{self.expense_number} - {self.description[:50]}"

    def clean(self):
        """Model validation"""
        super().clean()

        # Validate total amount
        calculated_total = self.amount + self.tax_amount
        if abs(self.total_amount - calculated_total) > Decimal('0.01'):
            raise ValidationError(
                _("Total amount must equal amount + tax amount")
            )

        # Validate payment amount
        if self.amount_paid > self.total_amount:
            raise ValidationError(
                _("Amount paid cannot exceed total amount")
            )

        # Validate dates
        if self.due_date and self.expense_date and self.due_date < self.expense_date:
            raise ValidationError(
                _("Due date cannot be before expense date")
            )

    def save(self, *args, **kwargs):
        # Auto-generate expense number
        if not self.expense_number:
            self.expense_number = self._generate_expense_number()

        # Calculate total if not set
        if not self.total_amount or self.total_amount == 0:
            self.total_amount = self.amount + self.tax_amount

        # Auto-calculate tax if tax rate is set
        if self.tax_rate and not self.tax_amount:
            self.tax_amount = (self.amount * self.tax_rate / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            self.total_amount = self.amount + self.tax_amount

        # Set due date based on vendor payment terms
        if not self.due_date and self.vendor:
            days = self.vendor.payment_term_days
            self.due_date = self.expense_date + timedelta(days=days)

        # Update status based on payment
        if self.amount_paid >= self.total_amount and self.status != 'PAID':
            self.status = 'PAID'
            if not self.payment_date:
                self.payment_date = timezone.now().date()
        elif self.amount_paid > 0 and self.amount_paid < self.total_amount:
            self.status = 'PARTIALLY_PAID'

        self.full_clean()
        super().save(*args, **kwargs)

    def _generate_expense_number(self):
        """Generate unique expense number"""
        today = timezone.now()
        prefix = f"EXP-{today.strftime('%Y%m%d')}"

        # Get count of expenses today
        count = Expense.objects.filter(
            expense_number__startswith=prefix
        ).count() + 1

        return f"{prefix}-{count:04d}"

    @property
    def amount_due(self):
        """Calculate outstanding amount"""
        return self.total_amount - self.amount_paid

    @property
    def is_overdue(self):
        """Check if expense is overdue"""
        if not self.due_date:
            return False
        return (
                self.status in ['APPROVED', 'PARTIALLY_PAID'] and
                timezone.now().date() > self.due_date
        )

    @property
    def days_overdue(self):
        """Calculate days overdue"""
        if not self.is_overdue:
            return 0
        return (timezone.now().date() - self.due_date).days

    def approve(self, approved_by, notes=''):
        """Approve expense"""
        if self.status != 'PENDING':
            raise ValidationError(_("Only pending expenses can be approved"))

        self.status = 'APPROVED'
        self.approved_by = approved_by
        self.approved_at = timezone.now()
        if notes:
            self.notes = f"{self.notes}\nApproval: {notes}" if self.notes else f"Approval: {notes}"
        self.save()

    def reject(self, rejected_by, reason):
        """Reject expense"""
        if self.status != 'PENDING':
            raise ValidationError(_("Only pending expenses can be rejected"))

        self.status = 'REJECTED'
        self.rejection_reason = reason
        self.notes = f"{self.notes}\nRejected by {rejected_by}: {reason}" if self.notes else f"Rejected by {rejected_by}: {reason}"
        self.save()

    def mark_as_paid(self, paid_by, payment_method, payment_reference='', payment_date=None):
        """Mark expense as paid"""
        if self.status not in ['APPROVED', 'PARTIALLY_PAID']:
            raise ValidationError(_("Only approved expenses can be marked as paid"))

        self.status = 'PAID'
        self.paid_by = paid_by
        self.payment_method = payment_method
        self.payment_reference = payment_reference
        self.payment_date = payment_date or timezone.now().date()
        self.amount_paid = self.total_amount
        self.save()

    def cancel(self, cancelled_by, reason):
        """Cancel expense"""
        if self.status == 'PAID':
            raise ValidationError(_("Paid expenses cannot be cancelled"))

        self.status = 'CANCELLED'
        self.notes = f"{self.notes}\nCancelled by {cancelled_by}: {reason}" if self.notes else f"Cancelled by {cancelled_by}: {reason}"
        self.save()


class ExpenseSplit(models.Model):
    """Split expenses across multiple stores/departments"""

    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='splits',
        verbose_name=_("Expense")
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.PROTECT,
        related_name='expense_splits',
        verbose_name=_("Store")
    )
    allocation_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name=_("Allocation %")
    )
    allocated_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Allocated Amount")
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )

    class Meta:
        verbose_name = _("Expense Split")
        verbose_name_plural = _("Expense Splits")
        unique_together = [['expense', 'store']]

    def __str__(self):
        return f"{self.expense.expense_number} - {self.store.name} ({self.allocation_percentage}%)"

    def save(self, *args, **kwargs):
        # Calculate allocated amount based on percentage
        self.allocated_amount = (
                self.expense.total_amount * self.allocation_percentage / Decimal('100')
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        super().save(*args, **kwargs)


class ExpenseAttachment(models.Model):
    """Attachments for expenses (receipts, invoices, etc.)"""

    ATTACHMENT_TYPES = [
        ('RECEIPT', _('Receipt')),
        ('INVOICE', _('Invoice')),
        ('QUOTATION', _('Quotation')),
        ('DELIVERY_NOTE', _('Delivery Note')),
        ('CONTRACT', _('Contract')),
        ('PHOTO', _('Photo')),
        ('OTHER', _('Other Document')),
    ]

    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='attachments',
        verbose_name=_("Expense")
    )
    attachment_type = models.CharField(
        max_length=20,
        choices=ATTACHMENT_TYPES,
        default='RECEIPT',
        verbose_name=_("Attachment Type")
    )
    file = models.FileField(
        upload_to='expenses/attachments/%Y/%m/',
        verbose_name=_("File")
    )
    file_name = models.CharField(
        max_length=255,
        verbose_name=_("File Name")
    )
    file_size = models.PositiveIntegerField(
        verbose_name=_("File Size (bytes)")
    )
    mime_type = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("MIME Type")
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Description")
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_expense_attachments'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Expense Attachment")
        verbose_name_plural = _("Expense Attachments")
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.expense.expense_number} - {self.file_name}"

    def save(self, *args, **kwargs):
        if self.file:
            self.file_name = self.file.name
            self.file_size = self.file.size
        super().save(*args, **kwargs)


class RecurringExpense(models.Model):
    """Recurring expense schedules"""

    FREQUENCY_CHOICES = [
        ('DAILY', _('Daily')),
        ('WEEKLY', _('Weekly')),
        ('BIWEEKLY', _('Bi-weekly')),
        ('MONTHLY', _('Monthly')),
        ('QUARTERLY', _('Quarterly')),
        ('SEMI_ANNUAL', _('Semi-annual')),
        ('ANNUAL', _('Annual')),
    ]

    name = models.CharField(
        max_length=200,
        verbose_name=_("Schedule Name")
    )
    description = models.TextField(
        verbose_name=_("Description")
    )

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.PROTECT,
        related_name='recurring_expenses',
        verbose_name=_("Store")
    )
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,
        related_name='recurring_expenses',
        verbose_name=_("Category")
    )
    expense_type = models.CharField(
        max_length=20,
        choices=Expense.EXPENSE_TYPES,
        default='OTHER',
        verbose_name=_("Expense Type")
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recurring_expenses',
        verbose_name=_("Vendor")
    )

    # Recurring Details
    frequency = models.CharField(
        max_length=20,
        choices=FREQUENCY_CHOICES,
        default='MONTHLY',
        verbose_name=_("Frequency")
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Amount")
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=18.00,
        verbose_name=_("Tax Rate %")
    )

    start_date = models.DateField(
        verbose_name=_("Start Date")
    )
    end_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("End Date"),
        help_text=_("Leave blank for indefinite")
    )
    next_occurrence = models.DateField(
        verbose_name=_("Next Occurrence")
    )

    # Auto-processing
    auto_approve = models.BooleanField(
        default=False,
        verbose_name=_("Auto Approve"),
        help_text=_("Automatically approve generated expenses")
    )
    auto_pay = models.BooleanField(
        default=False,
        verbose_name=_("Auto Pay"),
        help_text=_("Automatically mark as paid (use with caution)")
    )
    payment_method = models.CharField(
        max_length=20,
        choices=Expense.PAYMENT_METHODS,
        blank=True,
        verbose_name=_("Payment Method")
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_recurring_expenses'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Recurring Expense")
        verbose_name_plural = _("Recurring Expenses")
        ordering = ['next_occurrence']

    def __str__(self):
        return f"{self.name} - {self.get_frequency_display()}"

    def calculate_next_occurrence(self):
        """Calculate next occurrence date"""
        from dateutil.relativedelta import relativedelta

        current = self.next_occurrence

        if self.frequency == 'DAILY':
            return current + timedelta(days=1)
        elif self.frequency == 'WEEKLY':
            return current + timedelta(weeks=1)
        elif self.frequency == 'BIWEEKLY':
            return current + timedelta(weeks=2)
        elif self.frequency == 'MONTHLY':
            return current + relativedelta(months=1)
        elif self.frequency == 'QUARTERLY':
            return current + relativedelta(months=3)
        elif self.frequency == 'SEMI_ANNUAL':
            return current + relativedelta(months=6)
        elif self.frequency == 'ANNUAL':
            return current + relativedelta(years=1)

        return current

    def generate_expense(self):
        """Generate expense from this schedule"""
        if not self.is_active:
            return None

        if self.end_date and self.next_occurrence > self.end_date:
            self.is_active = False
            self.save()
            return None

        # Calculate tax
        tax_amount = (self.amount * self.tax_rate / Decimal('100')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        total_amount = self.amount + tax_amount

        # Create expense
        expense = Expense.objects.create(
            store=self.store,
            category=self.category,
            expense_type=self.expense_type,
            vendor=self.vendor,
            description=f"{self.description} ({self.get_frequency_display()})",
            expense_date=self.next_occurrence,
            amount=self.amount,
            tax_amount=tax_amount,
            tax_rate=self.tax_rate,
            total_amount=total_amount,
            is_recurring=True,
            recurring_schedule=self,
            status='APPROVED' if self.auto_approve else 'PENDING',
            payment_method=self.payment_method if self.auto_pay else '',
            created_by=self.created_by,
        )

        if self.auto_pay:
            expense.mark_as_paid(
                paid_by=self.created_by,
                payment_method=self.payment_method,
                payment_reference=f"Auto-payment: {self.name}"
            )

        # Update next occurrence
        self.next_occurrence = self.calculate_next_occurrence()
        self.save()

        return expense


class PettyCash(models.Model):
    """Petty cash management per store"""

    store = models.OneToOneField(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='petty_cash',
        verbose_name=_("Store")
    )
    opening_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Opening Balance")
    )
    current_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Current Balance")
    )
    maximum_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Maximum Limit")
    )
    minimum_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Minimum Balance Alert")
    )

    custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='custodian_petty_cash',
        verbose_name=_("Custodian"),
        help_text=_("Person responsible for petty cash")
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )

    last_reconciled = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Reconciled")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Petty Cash")
        verbose_name_plural = _("Petty Cash Accounts")

    def __str__(self):
        return f"Petty Cash - {self.store.name}"

    @property
    def total_disbursed(self):
        """Total amount disbursed"""
        result = self.transactions.filter(
            transaction_type='DISBURSEMENT'
        ).aggregate(total=Sum('amount'))
        return result['total'] or Decimal('0.00')

    @property
    def total_replenished(self):
        """Total amount replenished"""
        result = self.transactions.filter(
            transaction_type='REPLENISHMENT'
        ).aggregate(total=Sum('amount'))
        return result['total'] or Decimal('0.00')

    @property
    def needs_replenishment(self):
        """Check if petty cash needs replenishment"""
        return self.current_balance < self.minimum_balance

    def replenish(self, amount, replenished_by, notes=''):
        """Replenish petty cash"""
        if self.current_balance + amount > self.maximum_limit:
            raise ValidationError(
                _("Replenishment would exceed maximum limit")
            )

        PettyCashTransaction.objects.create(
            petty_cash=self,
            transaction_type='REPLENISHMENT',
            amount=amount,
            processed_by=replenished_by,
            notes=notes
        )

        self.current_balance += amount
        self.save()

    def disburse(self, amount, disbursed_by, expense, notes=''):
        """Disburse petty cash"""
        if amount > self.current_balance:
            raise ValidationError(_("Insufficient petty cash balance"))

        PettyCashTransaction.objects.create(
            petty_cash=self,
            transaction_type='DISBURSEMENT',
            amount=amount,
            expense=expense,
            processed_by=disbursed_by,
            notes=notes
        )

        self.current_balance -= amount
        self.save()


class PettyCashTransaction(models.Model):
    """Petty cash transactions"""

    TRANSACTION_TYPES = [
        ('REPLENISHMENT', _('Replenishment')),
        ('DISBURSEMENT', _('Disbursement')),
        ('ADJUSTMENT', _('Adjustment')),
    ]

    petty_cash = models.ForeignKey(
        PettyCash,
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name=_("Petty Cash Account")
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPES,
        verbose_name=_("Transaction Type")
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Amount")
    )
    expense = models.ForeignKey(
        Expense,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='petty_cash_transactions',
        verbose_name=_("Related Expense")
    )
    reference_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Reference Number")
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='petty_cash_transactions',
        verbose_name=_("Processed By")
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )
    balance_after = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name=_("Balance After Transaction")
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Petty Cash Transaction")
        verbose_name_plural = _("Petty Cash Transactions")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount}"

    def save(self, *args, **kwargs):
        # Generate reference number
        if not self.reference_number:
            today = timezone.now()
            prefix = f"PC-{today.strftime('%Y%m%d')}"
            count = PettyCashTransaction.objects.filter(
                reference_number__startswith=prefix
            ).count() + 1
            self.reference_number = f"{prefix}-{count:04d}"

        # Record balance after transaction
        self.balance_after = self.petty_cash.current_balance

        super().save(*args, **kwargs)


class ExpenseApprovalFlow(models.Model):
    """Define approval workflows for expense categories"""

    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.CASCADE,
        related_name='approval_flows',
        verbose_name=_("Category")
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='expense_approval_flows',
        verbose_name=_("Store"),
        help_text=_("Leave blank for company-wide flow")
    )
    approval_level = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Approval Level"),
        help_text=_("Order of approval (1 = first approver)")
    )
    approver_role = models.ForeignKey(
        'auth.Group',
        on_delete=models.CASCADE,
        related_name='expense_approval_flows',
        verbose_name=_("Approver Role")
    )
    minimum_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("Minimum Amount"),
        help_text=_("Minimum expense amount requiring this approval")
    )
    maximum_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("Maximum Amount")
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )

    class Meta:
        verbose_name = _("Expense Approval Flow")
        verbose_name_plural = _("Expense Approval Flows")
        ordering = ['category', 'approval_level']
        unique_together = [['category', 'store', 'approval_level']]

    def __str__(self):
        return f"{self.category.name} - Level {self.approval_level}"


class ExpenseApproval(models.Model):
    """Track individual expense approvals"""

    STATUS_CHOICES = [
        ('PENDING', _('Pending')),
        ('APPROVED', _('Approved')),
        ('REJECTED', _('Rejected')),
    ]

    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='approvals',
        verbose_name=_("Expense")
    )
    approval_level = models.PositiveIntegerField(
        verbose_name=_("Approval Level")
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='expense_approvals',
        verbose_name=_("Approver")
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING',
        verbose_name=_("Status")
    )
    comments = models.TextField(
        blank=True,
        verbose_name=_("Comments")
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Decision Date")
    )

    class Meta:
        verbose_name = _("Expense Approval")
        verbose_name_plural = _("Expense Approvals")
        ordering = ['approval_level']
        unique_together = [['expense', 'approval_level']]

    def __str__(self):
        return f"{self.expense.expense_number} - Level {self.approval_level}"


class EmployeeReimbursement(models.Model):
    """Employee expense reimbursement claims"""

    STATUS_CHOICES = [
        ('DRAFT', _('Draft')),
        ('SUBMITTED', _('Submitted')),
        ('APPROVED', _('Approved')),
        ('REJECTED', _('Rejected')),
        ('PAID', _('Paid')),
    ]

    reimbursement_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("Reimbursement Number")
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reimbursements',
        verbose_name=_("Employee")
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.PROTECT,
        related_name='employee_reimbursements',
        verbose_name=_("Store")
    )

    claim_date = models.DateField(
        default=timezone.now,
        verbose_name=_("Claim Date")
    )
    description = models.TextField(
        verbose_name=_("Description")
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Total Amount")
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT',
        verbose_name=_("Status")
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_reimbursements',
        verbose_name=_("Approved By")
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Approved At")
    )

    paid_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Paid Date")
    )
    payment_method = models.CharField(
        max_length=20,
        choices=Expense.PAYMENT_METHODS,
        blank=True,
        verbose_name=_("Payment Method")
    )
    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Payment Reference")
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Employee Reimbursement")
        verbose_name_plural = _("Employee Reimbursements")
        ordering = ['-claim_date']

    def __str__(self):
        return f"{self.reimbursement_number} - {self.employee.get_full_name()}"

    def save(self, *args, **kwargs):
        if not self.reimbursement_number:
            today = timezone.now()
            prefix = f"REIMB-{today.strftime('%Y%m%d')}"
            count = EmployeeReimbursement.objects.filter(
                reimbursement_number__startswith=prefix
            ).count() + 1
            self.reimbursement_number = f"{prefix}-{count:04d}"

        super().save(*args, **kwargs)


class ReimbursementItem(models.Model):
    """Individual items in a reimbursement claim"""

    reimbursement = models.ForeignKey(
        EmployeeReimbursement,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_("Reimbursement")
    )
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,
        related_name='reimbursement_items',
        verbose_name=_("Category")
    )
    description = models.CharField(
        max_length=200,
        verbose_name=_("Description")
    )
    expense_date = models.DateField(
        verbose_name=_("Expense Date")
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Amount")
    )
    receipt_number = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Receipt Number")
    )

    class Meta:
        verbose_name = _("Reimbursement Item")
        verbose_name_plural = _("Reimbursement Items")

    def __str__(self):
        return f"{self.description} - {self.amount}"


class ExpenseAuditLog(models.Model):
    """Comprehensive audit trail for expense operations"""

    ACTION_CHOICES = [
        ('CREATED', _('Created')),
        ('UPDATED', _('Updated')),
        ('SUBMITTED', _('Submitted for Approval')),
        ('APPROVED', _('Approved')),
        ('REJECTED', _('Rejected')),
        ('PAID', _('Marked as Paid')),
        ('CANCELLED', _('Cancelled')),
        ('ATTACHMENT_ADDED', _('Attachment Added')),
        ('ATTACHMENT_REMOVED', _('Attachment Removed')),
    ]

    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='audit_logs',
        verbose_name=_("Expense")
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        verbose_name=_("Action")
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='expense_audit_logs',
        verbose_name=_("User")
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Timestamp")
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP Address")
    )
    session = models.ForeignKey(
        'stores.UserDeviceSession',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expense_audit_logs',
        verbose_name=_("Device Session")
    )
    old_values = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Old Values")
    )
    new_values = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("New Values")
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )

    class Meta:
        verbose_name = _("Expense Audit Log")
        verbose_name_plural = _("Expense Audit Logs")
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['expense', '-timestamp']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.expense.expense_number} - {self.get_action_display()} by {self.user}"