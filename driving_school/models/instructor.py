from django.db import models


class Instructor(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    license_number = models.CharField(max_length=50, blank=True)
    license_expiry = models.DateField(null=True, blank=True)
    photo = models.ImageField(upload_to='driving_school/instructors/', null=True, blank=True)
    specializations = models.CharField(
        max_length=500, blank=True,
        help_text="Comma-separated license classes they can teach e.g. Class B, Class C"
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['first_name', 'last_name']
        verbose_name = 'Instructor'
        verbose_name_plural = 'Instructors'

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def total_sessions(self):
        return self.sessions.count()

    @property
    def sessions_this_month(self):
        from django.utils import timezone
        now = timezone.now()
        return self.sessions.filter(
            date__year=now.year,
            date__month=now.month
        ).count()
