from django.db import models


class CourseCategory(models.TextChoices):
    CLASS_A = 'CLASS_A', 'Class A'
    CLASS_A1 = 'CLASS_A1', 'Class A1'
    CLASS_B = 'CLASS_B', 'Class B'
    CLASS_B1 = 'CLASS_B1', 'Class B1'
    CLASS_BE = 'CLASS_BE', 'Class BE'
    CLASS_C = 'CLASS_C', 'Class C'
    CLASS_C1 = 'CLASS_C1', 'Class C1'
    CLASS_C1E = 'CLASS_C1E', 'Class C1E'
    CLASS_CE = 'CLASS_CE', 'Class CE'
    CLASS_D = 'CLASS_D', 'Class D'
    CLASS_D1 = 'CLASS_D1', 'Class D1'
    CLASS_D1E = 'CLASS_D1E', 'Class D1E'
    CLASS_DE = 'CLASS_DE', 'Class DE'
    CLASS_F = 'CLASS_F', 'Class F'
    CLASS_G = 'CLASS_G', 'Class G'
    DRIVING_LESSONS = 'DRIVING_LESSONS', 'Driving Lessons'
    DRIVING_TEST_PREP = 'DRIVING_TEST_PREP', 'Driving Test Preparation'
    EXPRESS_PERMIT = 'EXPRESS_PERMIT', 'Express Permit'
    RENEWAL = 'RENEWAL', 'Renewal'
    EXTENSION = 'EXTENSION', 'Extension'
    OTHER = 'OTHER', 'Other'


class DrivingCourse(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True)
    category = models.CharField(max_length=30, choices=CourseCategory.choices, default=CourseCategory.OTHER)
    description = models.TextField(blank=True)
    duration_lessons = models.PositiveIntegerField(default=10, help_text="Number of lessons included")
    duration_days = models.PositiveIntegerField(default=30, help_text="Expected completion in days")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'Driving Course'
        verbose_name_plural = 'Driving Courses'

    def __str__(self):
        return f"{self.code} - {self.name}"
