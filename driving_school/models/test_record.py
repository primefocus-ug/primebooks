from django.db import models


class TestType(models.TextChoices):
    THEORY = 'theory', 'Theory Test'
    PRACTICAL = 'practical', 'Practical / Road Test'


class TestResult(models.TextChoices):
    PASS = 'pass', 'Pass'
    FAIL = 'fail', 'Fail'
    PENDING = 'pending', 'Pending / Not Yet Taken'


class TestRecord(models.Model):
    enrollment = models.ForeignKey(
        'driving_school.Enrollment',
        on_delete=models.PROTECT,
        related_name='test_records'
    )
    test_type = models.CharField(max_length=15, choices=TestType.choices)
    test_date = models.DateField()
    result = models.CharField(max_length=10, choices=TestResult.choices, default=TestResult.PENDING)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    max_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    test_center = models.CharField(max_length=200, blank=True)
    examiner_name = models.CharField(max_length=200, blank=True)
    certificate_number = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-test_date']
        verbose_name = 'Test Record'
        verbose_name_plural = 'Test Records'

    def __str__(self):
        return f"{self.enrollment.student} - {self.get_test_type_display()} - {self.get_result_display()}"

    @property
    def passed(self):
        return self.result == TestResult.PASS
