from django.db import models
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings
from decimal import Decimal
import uuid
from .validators import validate_file_size, validate_file_type, validate_expense_date


class ExpenseCategory(models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name=_("Category Name")
    )

    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_("Category Code")
    )

    description = models.TextField(
        blank=True,
        verbose_name=_("Description")
    )

    # GL Account mapping for accounting
    gl_account = models.CharField(max_length=255, null=True, blank=True)

    # Budget tracking
    monthly_budget = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("Monthly Budget")
    )

    # Approval settings
    requires_approval = models.BooleanField(
        default=True,
        verbose_name=_("Requires Approval")
    )

    approval_threshold = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("Auto-Approve Below Amount"),
        help_text=_("Expenses below this amount are auto-approved")
    )

    # Color for UI display
    color_code = models.CharField(
        max_length=7,
        default='#6c757d',
        verbose_name=_("Color Code")
    )

    icon = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Icon Class"),
        help_text=_("Font Awesome or similar icon class")
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
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

    def __str__(self):
        return self.name

    def get_monthly_spent(self, month=None, year=None):
        """Get total spent in this category for a given month"""
        from django.db.models import Sum

        if not month:
            month = timezone.now().month
        if not year:
            year = timezone.now().year

        total = self.expenses.filter(
            expense_date__month=month,
            expense_date__year=year,
            status='PAID'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        return total

    def get_budget_utilization(self):
        """Get current month budget utilization percentage"""
        if not self.monthly_budget:
            return None

        spent = self.get_monthly_spent()
        return (spent / self.monthly_budget) * 100


class Expense(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', _('Draft')),
        ('SUBMITTED', _('Submitted')),
        ('APPROVED', _('Approved')),
        ('REJECTED', _('Rejected')),
        ('PAID', _('Paid')),
        ('CANCELLED', _('Cancelled')),
    ]
    CATEGORY_CHOICES = [
        ('RENT', "Rent"),
        ('UTILITIES', "Utilities"),
        ('SALARY', "Salaries"),
    ]

    PAYMENT_METHODS = [
        ('CASH', _('Cash')),
        ('BANK_TRANSFER', _('Bank Transfer')),
        ('MOBILE_MONEY', _('Mobile Money')),
        ('COMPANY_CARD', _('Company Card')),
        ('CHEQUE', _('Cheque')),
        ('OTHER', _('Other')),
    ]

    # Identification
    expense_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name=_("Expense Number")
    )

    reference_number = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Reference Number"),
        help_text=_("Receipt or invoice number")
    )

    # Basic Information
    title = models.CharField(
        max_length=200,
        verbose_name=_("Expense Title"), default=''
    )

    description = models.TextField(
        verbose_name=_("Description"),
        help_text=_("Detailed description of the expense")
    )

    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        verbose_name=_("Category")
    )

    # Amount Information
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
        verbose_name=_("Amount")
    )

    currency = models.CharField(
        max_length=3,
        default='UGX',
        verbose_name=_("Currency")
    )

    # Tax information
    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Tax Amount")
    )

    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Tax Rate (%)")
    )

    # Dates
    expense_date = models.DateField(
        default=timezone.now,
        verbose_name=_("Expense Date"),
        validators=[validate_expense_date]  # Add validator
    )

    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Payment Due Date")
    )

    # Who and Where
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_expenses',
        verbose_name=_("Created By")
    )

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='expenses',
        verbose_name=_("Store/Branch")
    )

    # Vendor Information
    vendor_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Vendor/Supplier Name")
    )

    vendor_phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Vendor Phone")
    )

    vendor_email = models.EmailField(
        blank=True,
        verbose_name=_("Vendor Email")
    )

    vendor_tin = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Vendor TIN")
    )

    # Status and Approval
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT',
        db_index=True,
        verbose_name=_("Status")
    )

    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Submitted At")
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

    rejected_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Rejected At")
    )

    # Payment Information
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHODS,
        blank=True,
        verbose_name=_("Payment Method")
    )

    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paid_expenses',
        verbose_name=_("Paid By")
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Paid At")
    )

    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Payment Reference"),
        help_text=_("Transaction ID or reference")
    )

    # Notes
    notes = models.TextField(
        blank=True,
        verbose_name=_("Additional Notes")
    )

    admin_notes = models.TextField(
        blank=True,
        verbose_name=_("Admin Notes"),
        help_text=_("Internal notes not visible to expense creator")
    )

    # Flags
    is_reimbursable = models.BooleanField(
        default=False,
        verbose_name=_("Reimbursable"),
        help_text=_("Should this be reimbursed to the user?")
    )

    is_recurring = models.BooleanField(
        default=False,
        verbose_name=_("Recurring Expense")
    )

    is_billable = models.BooleanField(
        default=False,
        verbose_name=_("Billable to Customer"),
        help_text=_("Can this be billed to a customer?")
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Expense")
        verbose_name_plural = _("Expenses")
        ordering = ['-expense_date', '-created_at']
        indexes = [
            models.Index(fields=['expense_number']),
            models.Index(fields=['created_by', '-expense_date']),
            models.Index(fields=['status', '-expense_date']),
            models.Index(fields=['store', '-expense_date']),
            models.Index(fields=['category', '-expense_date']),
        ]
        permissions = [
            ('approve_expense', 'Can approve expenses'),
            ('reject_expense', 'Can reject expenses'),
            ('pay_expense', 'Can mark expenses as paid'),
            ('view_all_expenses', 'Can view all expenses'),
        ]

    def __str__(self):
        return f"{self.expense_number} - {self.title} ({self.amount} {self.currency})"

    def save(self, *args, **kwargs):
        # Auto-generate expense number
        if not self.expense_number:
            self.expense_number = self.generate_expense_number()

        # Calculate tax if rate is provided
        if self.tax_rate and not self.tax_amount:
            self.tax_amount = (self.amount * self.tax_rate / 100).quantize(
                Decimal('0.01')
            )

        super().save(*args, **kwargs)

    def generate_expense_number(self):
        """Generate unique expense number"""
        prefix = "EXP"
        date_str = timezone.now().strftime('%Y%m%d')

        # Get last expense number for today
        last_expense = Expense.objects.filter(
            expense_number__startswith=f"{prefix}-{date_str}"
        ).order_by('-expense_number').first()

        if last_expense:
            try:
                last_num = int(last_expense.expense_number.split('-')[-1])
                next_num = last_num + 1
            except (ValueError, IndexError):
                next_num = 1
        else:
            next_num = 1

        return f"{prefix}-{date_str}-{next_num:04d}"

    def submit_for_approval(self):
        """Submit expense for approval"""
        if self.status != 'DRAFT':
            raise ValueError("Only draft expenses can be submitted")

        self.status = 'SUBMITTED'
        self.submitted_at = timezone.now()
        self.save(update_fields=['status', 'submitted_at'])

    def approve(self, user):
        """Approve expense"""
        if self.status not in ['SUBMITTED', 'DRAFT']:
            raise ValueError("Expense cannot be approved in current status")

        self.status = 'APPROVED'
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at'])

    def reject(self, user, reason):
        """Reject expense"""
        if self.status not in ['SUBMITTED', 'DRAFT']:
            raise ValueError("Expense cannot be rejected in current status")

        self.status = 'REJECTED'
        self.rejection_reason = reason
        self.rejected_at = timezone.now()
        self.save(update_fields=['status', 'rejection_reason', 'rejected_at'])

    def mark_as_paid(self, user, payment_method, payment_reference=''):
        """Mark expense as paid"""
        if self.status != 'APPROVED':
            raise ValueError("Only approved expenses can be marked as paid")

        self.status = 'PAID'
        self.paid_by = user
        self.paid_at = timezone.now()
        self.payment_method = payment_method
        self.payment_reference = payment_reference
        self.save(update_fields=[
            'status', 'paid_by', 'paid_at',
            'payment_method', 'payment_reference'
        ])

    @property
    def total_amount(self):
        """Total amount including tax"""
        return self.amount + self.tax_amount

    @property
    def is_overdue(self):
        """Check if payment is overdue"""
        if self.status != 'APPROVED' or not self.due_date:
            return False
        return timezone.now().date() > self.due_date

    @property
    def days_pending(self):
        """Days since submission"""
        if self.submitted_at:
            return (timezone.now() - self.submitted_at).days
        return 0


class ExpenseAttachment(models.Model):
    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='attachments',
        verbose_name=_("Expense")
    )

    file = models.FileField(
        upload_to='expenses/attachments/%Y/%m/',
        verbose_name=_("File"),
        validators=[validate_file_size, validate_file_type]  # Add validators
    )

    filename = models.CharField(
        max_length=255,
        verbose_name=_("Filename"), default=''
    )

    file_type = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("File Type")
    )

    file_size = models.PositiveBigIntegerField(
        default=0,
        verbose_name=_("File Size (bytes)")
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Description")
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("Uploaded By")
    )

    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Uploaded At")
    )

    class Meta:
        verbose_name = _("Expense Attachment")
        verbose_name_plural = _("Expense Attachments")
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.filename

    def save(self, *args, **kwargs):
        if self.file:
            self.filename = self.file.name
            self.file_size = self.file.size
        super().save(*args, **kwargs)


class ExpenseComment(models.Model):
    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='comments',
        verbose_name=_("Expense")
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name=_("User")
    )

    comment = models.TextField(
        verbose_name=_("Comment")
    )

    is_internal = models.BooleanField(
        default=False,
        verbose_name=_("Internal Comment"),
        help_text=_("Only visible to approvers and admins")
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At")
    )

    class Meta:
        verbose_name = _("Expense Comment")
        verbose_name_plural = _("Expense Comments")
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.user.get_full_name()} on {self.expense.expense_number}"