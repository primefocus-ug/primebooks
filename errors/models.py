from django.db import models
from django.utils import timezone
from django.conf import settings


class ErrorLog(models.Model):
    """Model to track error occurrences"""
    error_code = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    user_agent = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    timestamp = models.DateTimeField(default=timezone.now)
    additional_info = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['error_code', 'timestamp']),
            models.Index(fields=['path']),
        ]

    def __str__(self):
        return f"Error {self.error_code} at {self.path} ({self.timestamp})"


class ErrorSummary(models.Model):
    """Summary of error occurrences by day"""
    date = models.DateField()
    error_code = models.CharField(max_length=10)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ['date', 'error_code']
        ordering = ['-date']