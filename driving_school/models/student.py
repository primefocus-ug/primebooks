from django.db import models


class GenderChoices(models.TextChoices):
    MALE = 'M', 'Male'
    FEMALE = 'F', 'Female'
    OTHER = 'O', 'Other'


class Student(models.Model):
    # Personal Info
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=1, choices=GenderChoices.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    national_id = models.CharField(max_length=50, blank=True)
    photo = models.ImageField(upload_to='driving_school/students/', null=True, blank=True)

    # Contact
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    # Emergency Contact
    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    emergency_contact_relation = models.CharField(max_length=100, blank=True)

    # Meta
    student_number = models.CharField(max_length=30, unique=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Student'
        verbose_name_plural = 'Students'

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def save(self, *args, **kwargs):
        if not self.student_number:
            import datetime
            year = datetime.date.today().year
            last = Student.objects.filter(
                student_number__startswith=f"DS{year}"
            ).order_by('student_number').last()
            if last:
                try:
                    seq = int(last.student_number[-4:]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            self.student_number = f"DS{year}{seq:04d}"
        super().save(*args, **kwargs)
