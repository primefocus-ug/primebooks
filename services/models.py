from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP
import uuid

User = get_user_model()


class ServiceCategory(models.Model):
    """Categories for organizing services"""
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subcategories'
    )

    # EFRIS Integration
    efris_commodity_category_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        default='1010101000',
        verbose_name="EFRIS Commodity Category ID"
    )
    efris_commodity_category_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        default='General Services',
        verbose_name="EFRIS Commodity Category Name"
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Service Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class ServiceType(models.Model):
    """Types of services available"""
    FIXED = 'fixed'
    HOURLY = 'hourly'
    TIERED = 'tiered'
    VARIABLE = 'variable'

    PRICING_TYPES = [
        (FIXED, 'Fixed Price'),
        (HOURLY, 'Hourly Rate'),
        (TIERED, 'Tiered Pricing'),
        (VARIABLE, 'Variable Pricing'),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    pricing_type = models.CharField(max_length=20, choices=PRICING_TYPES, default=FIXED)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_pricing_type_display()})"


class Service(models.Model):
    """Main Service model - Integrated with existing POS system"""

    # Link to Store (tenant-aware through store->branch->company)
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='services',
        help_text="Store offering this service"
    )

    # Basic Information
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        'inventory.Category',
        on_delete=models.SET_NULL,
        null=True,
        related_name='services'
    )
    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.PROTECT,
        related_name='services'
    )

    # Pricing (matches Product model structure)
    base_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    hourly_rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )

    # Tax Configuration (matches Product TAX_RATE_CHOICES)
    TAX_RATE_CHOICES = [
        ('A', 'Standard rate (18%)'),
        ('B', 'Zero rate (0%)'),
        ('C', 'Exempt (Not taxable)'),
        ('D', 'Deemed rate (18%)'),
        ('E', 'Excise Duty rate'),
    ]

    tax_rate = models.CharField(
        max_length=1,
        choices=TAX_RATE_CHOICES,
        default='A'
    )

    # Duration & Scheduling
    default_duration = models.IntegerField(
        null=True,
        blank=True,
        help_text="Duration in minutes"
    )
    requires_appointment = models.BooleanField(default=False)
    allow_online_booking = models.BooleanField(default=False)
    max_advance_booking_days = models.IntegerField(default=30)

    # Recurrence/Subscription
    is_recurring = models.BooleanField(default=False)
    recurrence_interval = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('biweekly', 'Bi-weekly'),
            ('monthly', 'Monthly'),
            ('quarterly', 'Quarterly'),
            ('yearly', 'Yearly'),
        ]
    )

    # Staff Requirements
    requires_staff = models.BooleanField(default=False)
    staff_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    # Inventory Integration
    consumes_inventory = models.BooleanField(default=False)

    # EFRIS Integration
    efris_goods_code = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="EFRIS Goods Code"
    )
    efris_goods_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="EFRIS Goods Name"
    )
    efris_is_uploaded = models.BooleanField(
        default=False,
        verbose_name="Uploaded to EFRIS"
    )
    efris_upload_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="EFRIS Upload Date"
    )

    # Status & Availability
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    available_online = models.BooleanField(default=True)

    # Metadata
    image = models.ImageField(upload_to='services/', null=True, blank=True)
    tags = models.CharField(max_length=255, blank=True)
    sort_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='services_created'
    )

    class Meta:
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['store', 'is_active']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        # Auto-populate EFRIS fields
        if not self.efris_goods_name:
            self.efris_goods_name = self.name
        if not self.efris_goods_code:
            self.efris_goods_code = self.code

        super().save(*args, **kwargs)

    def calculate_price(self, duration_minutes=None, tier_level=None):
        """Calculate service price based on pricing type"""
        if self.service_type.pricing_type == 'hourly' and duration_minutes and self.hourly_rate:
            hours = Decimal(duration_minutes) / Decimal(60)
            return self.hourly_rate * hours
        elif self.service_type.pricing_type == 'tiered' and tier_level:
            tier = self.pricing_tiers.filter(tier_level=tier_level).first()
            return tier.price if tier else self.base_price
        return self.base_price

    def calculate_tax(self, subtotal):
        """Calculate tax amount (matches Product tax calculation)"""
        if self.tax_rate in ['A', 'D']:
            return (subtotal * Decimal('0.18')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        elif self.tax_rate == 'B' or self.tax_rate == 'C':
            return Decimal('0.00')
        return Decimal('0.00')


class ServicePricingTier(models.Model):
    """Tiered pricing for services"""
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name='pricing_tiers'
    )
    tier_name = models.CharField(max_length=50)
    tier_level = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['service', 'tier_level']
        unique_together = ['service', 'tier_level']

    def __str__(self):
        return f"{self.service.name} - {self.tier_name}"


class ServiceResource(models.Model):
    """Inventory consumed by services - Integrated with Product model"""
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name='resources'
    )
    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.CASCADE,
        related_name='service_usage'
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(0.001)]
    )
    is_optional = models.BooleanField(default=False)

    class Meta:
        ordering = ['service', 'product']
        unique_together = ['service', 'product']

    def __str__(self):
        return f"{self.service.name} - {self.product.name} ({self.quantity})"


class ServicePackage(models.Model):
    """Bundled services"""
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='service_packages'
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    validity_days = models.IntegerField(
        null=True,
        blank=True,
        help_text="Days package is valid after purchase"
    )
    max_uses = models.IntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of times package can be used"
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def calculate_total_value(self):
        """Calculate total value of services in package"""
        return sum(
            item.service.base_price * item.quantity
            for item in self.items.all()
        )

    def calculate_savings(self):
        """Calculate savings amount"""
        total_value = self.calculate_total_value()
        return total_value - self.price


class ServicePackageItem(models.Model):
    """Items in a service package"""
    package = models.ForeignKey(
        ServicePackage,
        on_delete=models.CASCADE,
        related_name='items'
    )
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['package', 'sort_order']
        unique_together = ['package', 'service']

    def __str__(self):
        return f"{self.package.name} - {self.service.name} (x{self.quantity})"


class ServiceAppointment(models.Model):
    """Service appointments/bookings - Integrated with Customer and Store"""
    SCHEDULED = 'scheduled'
    CONFIRMED = 'confirmed'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    NO_SHOW = 'no_show'

    STATUS_CHOICES = [
        (SCHEDULED, 'Scheduled'),
        (CONFIRMED, 'Confirmed'),
        (IN_PROGRESS, 'In Progress'),
        (COMPLETED, 'Completed'),
        (CANCELLED, 'Cancelled'),
        (NO_SHOW, 'No Show'),
    ]

    appointment_number = models.CharField(max_length=50, unique=True)
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name='appointments'
    )
    pricing_tier = models.ForeignKey(
        ServicePricingTier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Customer Information (Integrated with existing Customer model)
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='service_appointments'
    )

    # Store (for tenant awareness)
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.PROTECT,
        related_name='service_appointments'
    )

    # Scheduling
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    duration_minutes = models.IntegerField()

    # Staff Assignment (Integrated with CustomUser)
    assigned_staff = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_appointments'
    )

    # Pricing
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )

    # Status & Notes
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=SCHEDULED)
    notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)

    # Tracking
    actual_start_time = models.DateTimeField(null=True, blank=True)
    actual_end_time = models.DateTimeField(null=True, blank=True)

    # Reminders
    reminder_sent = models.BooleanField(default=False)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='appointments_created'
    )

    class Meta:
        ordering = ['-scheduled_date', '-scheduled_time']
        indexes = [
            models.Index(fields=['scheduled_date', 'scheduled_time']),
            models.Index(fields=['status']),
            models.Index(fields=['store', 'scheduled_date']),
            models.Index(fields=['customer']),
        ]

    def __str__(self):
        return f"{self.appointment_number} - {self.service.name} ({self.scheduled_date})"

    def save(self, *args, **kwargs):
        if not self.appointment_number:
            self.appointment_number = self.generate_appointment_number()
        if not self.duration_minutes:
            self.duration_minutes = self.service.default_duration or 60

        # Auto-set store from service if not set
        if not self.store_id:
            self.store = self.service.store

        super().save(*args, **kwargs)

    @staticmethod
    def generate_appointment_number():
        """Generate unique appointment number"""
        import datetime
        prefix = "APT"
        date_part = datetime.datetime.now().strftime("%Y%m%d")
        last = ServiceAppointment.objects.filter(
            appointment_number__startswith=f"{prefix}{date_part}"
        ).order_by('-appointment_number').first()

        if last:
            last_num = int(last.appointment_number[-4:])
            new_num = last_num + 1
        else:
            new_num = 1

        return f"{prefix}{date_part}{new_num:04d}"


class ServiceExecution(models.Model):
    """Track actual service delivery - Can link to Sale"""
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    ON_HOLD = 'on_hold'
    CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (IN_PROGRESS, 'In Progress'),
        (COMPLETED, 'Completed'),
        (ON_HOLD, 'On Hold'),
        (CANCELLED, 'Cancelled'),
    ]

    execution_number = models.CharField(max_length=50, unique=True)
    appointment = models.OneToOneField(
        ServiceAppointment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='execution'
    )
    service = models.ForeignKey(Service, on_delete=models.PROTECT)

    # Link to Sale (for billing integration)
    sale = models.ForeignKey(
        'sales.Sale',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_executions'
    )

    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='services_performed'
    )

    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    actual_duration_minutes = models.IntegerField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)

    # Work Details
    work_description = models.TextField(blank=True)
    findings = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)

    # Quality & Customer Satisfaction
    quality_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    customer_feedback = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_time']
        indexes = [
            models.Index(fields=['status', 'start_time']),
            models.Index(fields=['performed_by', 'start_time']),
        ]

    def __str__(self):
        return f"{self.execution_number} - {self.service.name}"

    def save(self, *args, **kwargs):
        if not self.execution_number:
            self.execution_number = self.generate_execution_number()
        if self.end_time and self.start_time:
            delta = self.end_time - self.start_time
            self.actual_duration_minutes = int(delta.total_seconds() / 60)
        super().save(*args, **kwargs)

    @staticmethod
    def generate_execution_number():
        """Generate unique execution number"""
        import datetime
        prefix = "EXE"
        date_part = datetime.datetime.now().strftime("%Y%m%d")
        last = ServiceExecution.objects.filter(
            execution_number__startswith=f"{prefix}{date_part}"
        ).order_by('-execution_number').first()

        if last:
            last_num = int(last.execution_number[-4:])
            new_num = last_num + 1
        else:
            new_num = 1

        return f"{prefix}{date_part}{new_num:04d}"


class ServiceDiscount(models.Model):
    """Discount rules for services"""
    PERCENTAGE = 'percentage'
    FIXED = 'fixed'

    DISCOUNT_TYPES = [
        (PERCENTAGE, 'Percentage'),
        (FIXED, 'Fixed Amount'),
    ]

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='service_discounts'
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPES, default=PERCENTAGE)
    value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )

    # Applicability
    services = models.ManyToManyField(Service, blank=True, related_name='discounts')
    categories = models.ManyToManyField(ServiceCategory, blank=True, related_name='discounts')

    # Conditions
    min_purchase_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )
    max_discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )

    # Validity
    start_date = models.DateField()
    end_date = models.DateField()
    max_uses = models.IntegerField(null=True, blank=True)
    uses_count = models.IntegerField(default=0)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def is_valid(self):
        """Check if discount is currently valid"""
        today = timezone.now().date()

        if not self.is_active:
            return False
        if today < self.start_date or today > self.end_date:
            return False
        if self.max_uses and self.uses_count >= self.max_uses:
            return False
        return True

    def calculate_discount(self, amount):
        """Calculate discount amount for given amount"""
        if not self.is_valid():
            return Decimal(0)

        if self.discount_type == self.PERCENTAGE:
            discount = amount * (self.value / Decimal(100))
        else:
            discount = self.value

        if self.max_discount_amount:
            discount = min(discount, self.max_discount_amount)

        return discount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class StaffServiceSkill(models.Model):
    """Track which staff can perform which services"""
    BEGINNER = 'beginner'
    INTERMEDIATE = 'intermediate'
    ADVANCED = 'advanced'
    EXPERT = 'expert'

    PROFICIENCY_LEVELS = [
        (BEGINNER, 'Beginner'),
        (INTERMEDIATE, 'Intermediate'),
        (ADVANCED, 'Advanced'),
        (EXPERT, 'Expert'),
    ]

    staff = models.ForeignKey(User, on_delete=models.CASCADE, related_name='service_skills')
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='staff_skills')
    proficiency_level = models.CharField(
        max_length=20,
        choices=PROFICIENCY_LEVELS,
        default=INTERMEDIATE
    )
    certification_number = models.CharField(max_length=100, blank=True)
    certification_date = models.DateField(null=True, blank=True)
    certification_expiry = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['staff', 'service']
        ordering = ['staff', 'service']

    def __str__(self):
        return f"{self.staff.get_full_name()} - {self.service.name} ({self.get_proficiency_level_display()})"


class ServiceReview(models.Model):
    """Customer reviews for services"""
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='reviews')
    execution = models.OneToOneField(
        ServiceExecution,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='service_reviews'
    )

    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    review_text = models.TextField(blank=True)

    # Staff Rating
    staff_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )

    is_verified = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)

    helpful_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['service', 'is_published', 'rating']),
        ]

    def __str__(self):
        return f"{self.service.name} - {self.rating}★ by {self.customer.name}"
