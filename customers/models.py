from decimal import Decimal

from django.db import models
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
import uuid
from primebooks.mixins import OfflineIDMixin
from .efris import  EFRISCustomerMixin


class Customer(OfflineIDMixin, models.Model,EFRISCustomerMixin):
    CUSTOMER_TYPES = [
        ('INDIVIDUAL', _('Individual')),
        ('BUSINESS', _('Business')),
        ('GOVERNMENT', _('Government Agency')),
        ('NGO', _('Non-Profit Organization')),
    ]

    EFRIS_CUSTOMER_TYPES = [
        ('1', _('Individual')),
        ('2', _('Business')),
        ('3', _('Government')),
        ('4', _('NGO')),
    ]

    # eFRIS Registration Status
    EFRIS_STATUS_CHOICES = [
        ('NOT_REGISTERED', _('Not Registered')),
        ('PENDING', _('Registration Pending')),
        ('REGISTERED', _('Registered')),
        ('FAILED', _('Registration Failed')),
        ('UPDATED', _('Updated')),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    customer_id = models.CharField(
        max_length=36,
        unique=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("Customer ID")
    )

    customer_type = models.CharField(
        max_length=20,
        choices=CUSTOMER_TYPES,
        default='INDIVIDUAL',
        verbose_name=_("Customer Type")
    )
    name = models.CharField(max_length=255, verbose_name=_("Customer Name"), blank=True, null=True)
    store = models.ForeignKey('stores.Store', default='1', on_delete=models.CASCADE, related_name="customers")
    email = models.EmailField(blank=True, null=True, verbose_name=_("Email Address"))
    phone = models.CharField(
        max_length=20,
        validators=[RegexValidator(r'^\+?[0-9]+$', 'Enter a valid phone number.')],
        verbose_name=_("Phone Number"),
        blank=True,null=True
    )
    tin = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("Tax Identification Number (TIN)"),
        help_text=_("Required for B2B transactions")
    )
    nin = models.CharField(max_length=20, blank=True, null=True, verbose_name=_("National ID Number (NIN)"))
    brn = models.CharField(max_length=20, blank=True, null=True, verbose_name=_("Business Registration Number (BRN)"))
    physical_address = models.TextField(blank=True, null=True, verbose_name=_("Physical Address"))
    postal_address = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("Postal Address"))
    district = models.CharField(max_length=100, blank=True, null=True, verbose_name=_("District"))
    country = models.CharField(max_length=100, default="Uganda", verbose_name=_("Country"))
    is_vat_registered = models.BooleanField(default=False, verbose_name=_("VAT Registered"))
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name=_("Credit Limit"))
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))

    # eFRIS Integration Fields
    efris_customer_type = models.CharField(
        max_length=10,
        choices=EFRIS_CUSTOMER_TYPES,
        blank=True,
        null=True,
        verbose_name=_("eFRIS Customer Type"),
        help_text=_("Customer type code for eFRIS system")
    )
    efris_customer_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        unique=True,
        verbose_name=_("eFRIS Customer ID"),
        help_text=_("Unique customer ID from eFRIS system")
    )
    efris_status = models.CharField(
        max_length=20,
        choices=EFRIS_STATUS_CHOICES,
        default='NOT_REGISTERED',
        verbose_name=_("eFRIS Registration Status")
    )
    efris_registered_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("eFRIS Registration Date")
    )
    efris_last_sync = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Last eFRIS Sync")
    )
    efris_reference_no = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("eFRIS Reference Number")
    )
    efris_sync_error = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("eFRIS Sync Error"),
        help_text=_("Last error message from eFRIS sync")
    )

    passport_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("Passport Number"),
        help_text=_("For foreign customers")
    )
    driving_license = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("Driving License Number")
    )
    voter_id = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("Voter ID Number")
    )
    alien_id = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("Alien ID Number"),
        help_text=_("For non-citizen residents")
    )
    credit_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name=_("Current Credit Balance"),
        help_text=_("Total outstanding amount owed")
    )

    credit_available = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name=_("Available Credit"),
        help_text=_("Credit limit minus current balance")
    )

    allow_credit = models.BooleanField(
        default=False,
        verbose_name=_("Allow Credit Sales"),
        help_text=_("Whether this customer can buy on credit")
    )

    credit_days = models.PositiveIntegerField(
        default=30,
        verbose_name=_("Credit Payment Days"),
        help_text=_("Number of days allowed for credit payment")
    )

    last_credit_review = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Last Credit Review Date")
    )

    credit_status = models.CharField(
        max_length=20,
        choices=[
            ('GOOD', _('Good Standing')),
            ('WARNING', _('Payment Warning')),
            ('SUSPENDED', _('Credit Suspended')),
            ('BLOCKED', _('Blocked')),
        ],
        default='GOOD',
        verbose_name=_("Credit Status")
    )
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_customers',
        verbose_name=_("Created By")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Customer")
        verbose_name_plural = _("Customers")
        ordering = ['name']
        indexes = [
            models.Index(fields=['tin']),
            models.Index(fields=['nin']),
            models.Index(fields=['brn']),
            models.Index(fields=['phone']),
            models.Index(fields=['efris_customer_id']),
            models.Index(fields=['efris_status']),
        ]

    def __str__(self):
        return f"{self.name} ({self.customer_id})"

    def clean(self):
        super().clean()

        # Ensure name and phone are strings and not empty
        if not self.name or not str(self.name).strip():
            raise ValidationError(_("Customer name is required"))

        if not self.phone or not str(self.phone).strip():
            raise ValidationError(_("Customer phone number is required"))

        # Validate based on customer type
        if self.customer_type in ['BUSINESS', 'GOVERNMENT', 'NGO']:
            # Ensure TIN is a string and not empty
            tin_value = str(self.tin).strip() if self.tin else ''
            if not tin_value:
                raise ValidationError(
                    _("Business, Government, and NGO customers must have a Tax Identification Number (TIN)")
                )

        # eFRIS validation
        if self.efris_status == 'REGISTERED' and not self.efris_customer_id:
            raise ValidationError(_("Registered customers must have eFRIS Customer ID"))

    def save(self, *args, **kwargs):
        # Helper function to safely normalize identification numbers
        def normalize_identification(value):
            if value is None:
                return ''
            # Convert to string if it's not already
            if not isinstance(value, str):
                value = str(value)
            # Strip whitespace and check if empty
            value = value.strip()
            return value.upper() if value else ''

        # Normalize identification numbers safely
        self.tin = normalize_identification(self.tin)
        self.nin = normalize_identification(self.nin)
        self.brn = normalize_identification(self.brn)
        self.passport_number = normalize_identification(self.passport_number)
        self.driving_license = normalize_identification(self.driving_license)
        self.voter_id = normalize_identification(self.voter_id)
        self.alien_id = normalize_identification(self.alien_id)

        # Set eFRIS customer type based on customer type
        if not self.efris_customer_type:
            efris_mapping = {
                'INDIVIDUAL': '1',
                'BUSINESS': '2',
                'GOVERNMENT': '3',
                'NGO': '4',
            }
            self.efris_customer_type = efris_mapping.get(self.customer_type, '1')

        # Validate before saving
        self.clean()

        super().save(*args, **kwargs)

    @property
    def tax_details(self):
        return {
            'customer_type': self.get_customer_type_display(),
            'tin': self.tin,
            'nin': self.nin,
            'brn': self.brn,
            'is_vat_registered': self.is_vat_registered,
            'customer_name': self.name,
            'customer_address': self.physical_address or self.postal_address,
            'efris_customer_id': self.efris_customer_id,
            'efris_status': self.get_efris_status_display(),
        }

    @property
    def primary_identification(self):
        """Get the primary identification number for this customer"""
        if self.customer_type == 'BUSINESS':
            return self.tin or self.brn
        elif self.customer_type == 'INDIVIDUAL':
            return self.nin or self.passport_number or self.driving_license
        return self.tin or self.nin or self.brn

    @property
    def total_outstanding(self):
        """Calculate total outstanding amount from unpaid invoices"""
        from django.db.models import Sum
        from sales.models import Sale

        outstanding = Sale.objects.filter(
            customer=self,
            document_type='INVOICE',
            payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
        ).aggregate(
            total=Sum('total_amount')
        )['total'] or Decimal('0')

        return outstanding

    @property
    def total_paid_amount(self):
        """Calculate total amount paid across all invoices"""
        from django.db.models import Sum
        from sales.models import Payment

        paid = Payment.objects.filter(
            sale__customer=self,
            is_voided=False
        ).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        return paid

    @property
    def overdue_amount(self):
        """Calculate overdue amount"""
        from django.db.models import Sum
        from sales.models import Sale

        overdue = Sale.objects.filter(
            customer=self,
            document_type='INVOICE',
            payment_status='OVERDUE'
        ).aggregate(
            total=Sum('total_amount')
        )['total'] or Decimal('0')

        return overdue

    @property
    def has_overdue_invoices(self):
        """Check if customer has any overdue invoices"""
        from sales.models import Sale

        return Sale.objects.filter(
            customer=self,
            document_type='INVOICE',
            payment_status='OVERDUE'
        ).exists()

    @property
    def can_purchase_on_credit(self):
        """Check if customer can make credit purchases"""
        if not self.allow_credit:
            return False, "Credit not allowed for this customer"

        if self.credit_status in ['SUSPENDED', 'BLOCKED']:
            return False, f"Credit {self.credit_status.lower()}"

        if self.has_overdue_invoices:
            return False, "Customer has overdue invoices"

        return True, "Credit allowed"

    def update_credit_balance(self):
        """Update credit balance and available credit"""
        self.credit_balance = self.total_outstanding
        self.credit_available = max(
            Decimal('0'),
            self.credit_limit - self.credit_balance
        )

        # Update credit status
        if self.has_overdue_invoices:
            if self.overdue_amount > (self.credit_limit * Decimal('0.5')):
                self.credit_status = 'SUSPENDED'
            else:
                self.credit_status = 'WARNING'
        elif self.credit_balance > self.credit_limit:
            self.credit_status = 'WARNING'
        else:
            self.credit_status = 'GOOD'

        self.save(update_fields=['credit_balance', 'credit_available', 'credit_status'])

    def check_credit_limit(self, amount):
        """Check if purchase amount is within credit limit"""
        if not self.allow_credit:
            return False, "Credit purchases not allowed"

        can_purchase, reason = self.can_purchase_on_credit
        if not can_purchase:
            return False, reason

        new_balance = self.credit_balance + Decimal(str(amount))

        if new_balance > self.credit_limit:
            return False, f"Credit limit exceeded. Available: {self.credit_available}, Requested: {amount}"

        return True, "Credit approved"

    @property
    def is_efris_registered(self):
        """Check if customer is registered in eFRIS"""
        return self.efris_status == 'REGISTERED'

    @property
    def can_sync_to_efris(self):
        """Check if customer has required data for eFRIS sync according to new requirements"""
        # All customers require name and phone
        if not (self.name and self.phone):
            return False

        # Business/Government customers require TIN
        if self.customer_type in ['BUSINESS', 'GOVERNMENT']:
            return bool(self.tin)

        # Individual customers - only name and phone required
        return True

    def get_efris_payload(self):
        """Generate payload for eFRIS customer registration/update"""
        payload = {
            'customerName': self.name.strip(),
            'customerType': self.efris_customer_type,
            'phoneNo': self.phone.strip(),
            'email': self.email.strip() if self.email else '',
            'address': (self.physical_address or self.postal_address or '').strip(),
        }

        # Add required TIN for business/government
        if self.customer_type in ['BUSINESS', 'GOVERNMENT'] and self.tin:
            payload['tin'] = self.tin.strip()

        # Add optional identification numbers
        if self.customer_type == 'INDIVIDUAL':
            if self.nin:
                payload['nin'] = self.nin.strip()
            if self.passport_number:
                payload['passportNo'] = self.passport_number.strip()

        # Add BRN if available (but not required)
        if self.brn:
            payload['businessRegistrationNo'] = self.brn.strip()

        # Add other optional identifiers
        if self.driving_license:
            payload['drivingLicenseNo'] = self.driving_license.strip()
        if self.voter_id:
            payload['voterIdNo'] = self.voter_id.strip()
        if self.alien_id:
            payload['alienIdNo'] = self.alien_id.strip()

        return payload

    def mark_efris_registered(self, efris_id, reference_no=None):
        """Mark customer as registered in eFRIS"""
        from django.utils import timezone

        self.efris_customer_id = efris_id
        self.efris_status = 'REGISTERED'
        self.efris_registered_at = timezone.now()
        self.efris_last_sync = timezone.now()
        if reference_no:
            self.efris_reference_no = reference_no
        self.efris_sync_error = None
        self.save()

    def mark_efris_error(self, error_message):
        """Mark customer with eFRIS sync error"""
        from django.utils import timezone

        self.efris_status = 'FAILED'
        self.efris_last_sync = timezone.now()
        self.efris_sync_error = error_message
        self.save()


class CustomerCreditStatement(OfflineIDMixin, models.Model):
    """Track all credit transactions for a customer"""

    TRANSACTION_TYPES = [
        ('INVOICE', _('Invoice Created')),
        ('PAYMENT', _('Payment Received')),
        ('CREDIT_NOTE', _('Credit Note')),
        ('ADJUSTMENT', _('Balance Adjustment')),
    ]

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='credit_statements'
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)

    sale = models.ForeignKey(
        'sales.Sale',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='credit_transactions'
    )

    payment = models.ForeignKey(
        'sales.Payment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)

    description = models.TextField()
    reference_number = models.CharField(max_length=100, blank=True)

    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Customer Credit Statement")
        verbose_name_plural = _("Customer Credit Statements")

    def __str__(self):
        return f"{self.customer.name} - {self.transaction_type} - {self.amount}"

class CustomerGroup(OfflineIDMixin, models.Model):
    name = models.CharField(max_length=100, verbose_name=_("Group Name"))
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name=_("Discount Percentage")
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    customers = models.ManyToManyField(
        Customer,
        related_name='groups',
        blank=True,
        verbose_name=_("Customers")
    )

    # eFRIS Integration
    auto_sync_to_efris = models.BooleanField(
        default=False,
        verbose_name=_("Auto Sync to eFRIS"),
        help_text=_("Automatically sync new customers in this group to eFRIS")
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Customer Group")
        verbose_name_plural = _("Customer Groups")
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def efris_registered_count(self):
        """Count of eFRIS registered customers in this group"""
        return self.customers.filter(efris_status='REGISTERED').count()

    @property
    def efris_pending_count(self):
        """Count of customers pending eFRIS registration in this group"""
        return self.customers.filter(efris_status__in=['NOT_REGISTERED', 'PENDING']).count()


class CustomerNote(OfflineIDMixin, models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='notes',
        verbose_name=_("Customer")
    )
    author = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("Author")
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    note = models.TextField(verbose_name=_("Note"))

    # Note categories
    NOTE_CATEGORIES = [
        ('GENERAL', _('General')),
        ('EFRIS', _('eFRIS Related')),
        ('TAX', _('Tax Information')),
        ('PAYMENT', _('Payment Related')),
        ('SUPPORT', _('Support Issue')),
    ]

    category = models.CharField(
        max_length=20,
        choices=NOTE_CATEGORIES,
        default='GENERAL',
        verbose_name=_("Category")
    )
    is_important = models.BooleanField(default=False, verbose_name=_("Important"))

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Customer Note")
        verbose_name_plural = _("Customer Notes")
        ordering = ['-created_at']

    def __str__(self):
        return f"Note for {self.customer.name} by {self.author}"


class EFRISCustomerSync(models.Model):
    """Track eFRIS synchronization attempts"""
    SYNC_TYPES = [
        ('REGISTER', _('Registration')),
        ('UPDATE', _('Update')),
        ('QUERY', _('Query')),
    ]

    SYNC_STATUS = [
        ('PENDING', _('Pending')),
        ('SUCCESS', _('Success')),
        ('FAILED', _('Failed')),
        ('RETRY', _('Retry Required')),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='efris_syncs',
        verbose_name=_("Customer")
    )
    sync_type = models.CharField(
        max_length=20,
        choices=SYNC_TYPES,
        verbose_name=_("Sync Type")
    )
    status = models.CharField(
        max_length=20,
        choices=SYNC_STATUS,
        default='PENDING',
        verbose_name=_("Status")
    )
    request_payload = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_("Request Payload")
    )
    response_data = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_("Response Data")
    )
    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Error Message")
    )
    efris_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("eFRIS Reference")
    )
    retry_count = models.IntegerField(default=0, verbose_name=_("Retry Count"))
    max_retries = models.IntegerField(default=3, verbose_name=_("Max Retries"))

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))
    processed_at = models.DateTimeField(blank=True, null=True, verbose_name=_("Processed At"))

    class Meta:
        verbose_name = _("eFRIS Customer Sync")
        verbose_name_plural = _("eFRIS Customer Syncs")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', 'sync_type']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.sync_type} - {self.customer.name} ({self.status})"

    @property
    def can_retry(self):
        """Check if sync can be retried"""
        return self.status == 'FAILED' and self.retry_count < self.max_retries

    def mark_success(self, response_data=None, efris_reference=None):
        """Mark sync as successful"""
        from django.utils import timezone

        self.status = 'SUCCESS'
        self.processed_at = timezone.now()
        if response_data:
            self.response_data = response_data
        if efris_reference:
            self.efris_reference = efris_reference
        self.save()

    def mark_failed(self, error_message, should_retry=True):
        """Mark sync as failed"""
        from django.utils import timezone

        self.error_message = error_message
        self.processed_at = timezone.now()

        if should_retry and self.retry_count < self.max_retries:
            self.status = 'RETRY'
            self.retry_count += 1
        else:
            self.status = 'FAILED'

        self.save()

        # Update customer status
        self.customer.mark_efris_error(error_message)