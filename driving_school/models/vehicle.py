from django.db import models


class TransmissionType(models.TextChoices):
    MANUAL = 'manual', 'Manual'
    AUTOMATIC = 'automatic', 'Automatic'


class VehicleStatus(models.TextChoices):
    AVAILABLE = 'available', 'Available'
    IN_USE = 'in_use', 'In Use'
    MAINTENANCE = 'maintenance', 'Under Maintenance'
    RETIRED = 'retired', 'Retired'


class Vehicle(models.Model):
    plate_number = models.CharField(max_length=20, unique=True)
    make = models.CharField(max_length=100, help_text="e.g. Toyota")
    model = models.CharField(max_length=100, help_text="e.g. Corolla")
    year = models.PositiveIntegerField(null=True, blank=True)
    color = models.CharField(max_length=50, blank=True)
    transmission = models.CharField(
        max_length=10,
        choices=TransmissionType.choices,
        default=TransmissionType.MANUAL
    )
    status = models.CharField(
        max_length=15,
        choices=VehicleStatus.choices,
        default=VehicleStatus.AVAILABLE
    )
    insurance_expiry = models.DateField(null=True, blank=True)
    service_due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['plate_number']
        verbose_name = 'Vehicle'
        verbose_name_plural = 'Vehicles'

    def __str__(self):
        return f"{self.plate_number} - {self.make} {self.model}"

    @property
    def display_name(self):
        return f"{self.make} {self.model} ({self.plate_number})"
