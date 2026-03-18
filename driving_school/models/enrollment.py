from django.db import models
from django.conf import settings


class EnrollmentStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    ACTIVE = 'active', 'Active'
    COMPLETED = 'completed', 'Completed'
    CANCELLED = 'cancelled', 'Cancelled'
    SUSPENDED = 'suspended', 'Suspended'


class PaymentMethod(models.TextChoices):
    CASH = 'cash', 'Cash'
    MOBILE_MONEY = 'mobile_money', 'Mobile Money'
    BANK_TRANSFER = 'bank_transfer', 'Bank Transfer'
    CHEQUE = 'cheque', 'Cheque'
    OTHER = 'other', 'Other'


class Enrollment(models.Model):
    student = models.ForeignKey(
        'driving_school.Student',
        on_delete=models.PROTECT,
        related_name='enrollments'
    )
    course = models.ForeignKey(
        'driving_school.DrivingCourse',
        on_delete=models.PROTECT,
        related_name='enrollments'
    )
    enrollment_number = models.CharField(max_length=30, unique=True, blank=True)
    date_enrolled = models.DateField(auto_now_add=True)
    expected_completion = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=EnrollmentStatus.choices, default=EnrollmentStatus.PENDING)

    # Financials
    agreed_fee = models.DecimalField(max_digits=12, decimal_places=2)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='ds_enrollments_created',
        db_constraint=False,
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Enrollment'
        verbose_name_plural = 'Enrollments'

    def __str__(self):
        return f"{self.enrollment_number} - {self.student}"

    @property
    def total_fee(self):
        return self.agreed_fee - self.discount

    @property
    def amount_paid(self):
        return sum(p.amount for p in self.payments.filter(is_voided=False))

    @property
    def balance(self):
        return self.total_fee - self.amount_paid

    @property
    def is_fully_paid(self):
        return self.balance <= 0

    @property
    def lessons_completed(self):
        return self.sessions.filter(status='completed').count()

    @property
    def lessons_remaining(self):
        total = self.course.duration_lessons
        return max(0, total - self.lessons_completed)

    def save(self, *args, **kwargs):
        if not self.enrollment_number:
            import datetime
            year = datetime.date.today().year
            last = Enrollment.objects.filter(
                enrollment_number__startswith=f"EN{year}"
            ).order_by('enrollment_number').last()
            if last:
                try:
                    seq = int(last.enrollment_number[-4:]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            self.enrollment_number = f"EN{year}{seq:04d}"
        super().save(*args, **kwargs)


class Payment(models.Model):
    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        related_name='payments'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    reference = models.CharField(max_length=100, blank=True, help_text="Receipt/transaction number")
    date_paid = models.DateField(auto_now_add=True)
    notes = models.TextField(blank=True)
    is_voided = models.BooleanField(default=False)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='ds_payments_received',
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_paid']
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'

    def __str__(self):
        return f"UGX {self.amount:,} - {self.enrollment}"
