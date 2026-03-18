from django.db import models


class SessionStatus(models.TextChoices):
    SCHEDULED = 'scheduled', 'Scheduled'
    COMPLETED = 'completed', 'Completed'
    MISSED = 'missed', 'Missed'
    CANCELLED = 'cancelled', 'Cancelled'
    RESCHEDULED = 'rescheduled', 'Rescheduled'


class LessonSession(models.Model):
    enrollment = models.ForeignKey(
        'driving_school.Enrollment',
        on_delete=models.PROTECT,
        related_name='sessions'
    )
    instructor = models.ForeignKey(
        'driving_school.Instructor',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sessions'
    )
    vehicle = models.ForeignKey(
        'driving_school.Vehicle',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sessions'
    )
    date = models.DateField()
    start_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField(default=60)
    status = models.CharField(
        max_length=15,
        choices=SessionStatus.choices,
        default=SessionStatus.SCHEDULED
    )
    lesson_number = models.PositiveIntegerField(null=True, blank=True)
    route_notes = models.TextField(blank=True, help_text="Areas/routes covered")
    instructor_notes = models.TextField(blank=True)
    student_performance = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-start_time']
        verbose_name = 'Lesson Session'
        verbose_name_plural = 'Lesson Sessions'

    def __str__(self):
        return f"{self.enrollment.student} - {self.date} {self.start_time}"

    @property
    def student(self):
        return self.enrollment.student
