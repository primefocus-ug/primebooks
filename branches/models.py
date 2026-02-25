from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
import uuid
from primebooks.mixins import OfflineIDMixin



class CompanyBranch(OfflineIDMixin, models.Model):
    """Enhanced company branch model with additional features."""
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='branches',
        verbose_name=_("Company")
    )
    name = models.CharField(max_length=255, verbose_name=_("Branch Name"))
    nin = models.CharField(max_length=20, blank=True, null=True, verbose_name=_("NIN"))
    code = models.CharField(max_length=10, blank=True, null=True, verbose_name=_("Branch Code"))
    location = models.CharField(max_length=255, verbose_name=_("Location"))
    efris_device_number = models.CharField(max_length=50, blank=True, null=True)
    tin = models.CharField(max_length=20, blank=True, null=True, verbose_name=_("TIN"))
    # Contact Information
    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                r'^\+?[0-9]+$',
                _('Enter a valid phone number.')
            )
        ],
        verbose_name=_("Branch Phone")
    )
    email = models.EmailField(max_length=255, blank=True, null=True, verbose_name=_("Branch Email"))
    address = models.TextField(blank=True, verbose_name=_("Physical Address"))
    
    # Branch Settings
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    is_main_branch = models.BooleanField(default=False, verbose_name=_("Main Branch"))
    allows_sales = models.BooleanField(default=True, verbose_name=_("Allows Sales"))
    allows_inventory = models.BooleanField(default=True, verbose_name=_("Manages Inventory"))
    
    # Manager Information
    manager_name = models.CharField(max_length=255, blank=True, verbose_name=_("Branch Manager"))
    manager_phone = models.CharField(max_length=20, blank=True, verbose_name=_("Manager Phone"))
    
    # Operating Hours
    operating_hours = models.JSONField(
        default=dict,
        help_text="Operating hours for each day of the week"
    )
    timezone = models.CharField(max_length=100, blank=True)
    
    # Metadata
    sort_order = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, verbose_name=_("Notes"))
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Company Branch")
        verbose_name_plural = _("Company Branches")
        unique_together = [('company', 'name'), ('company', 'code')]
        ordering = ['-is_main_branch', 'sort_order', 'name']
        indexes = [
            models.Index(fields=['company', 'is_active']),
            models.Index(fields=['is_main_branch']),
        ]

    def save(self, *args, **kwargs):
        # Ensure only one main branch per company
        if self.is_main_branch:
            CompanyBranch.objects.filter(
                company=self.company, 
                is_main_branch=True
            ).exclude(id=self.id).update(is_main_branch=False)
        
        # Auto-generate code if not provided
        if not self.code:
            existing_codes = CompanyBranch.objects.filter(
                company=self.company
            ).values_list('code', flat=True)
            
            counter = 1
            while f"BR{counter:03d}" in existing_codes:
                counter += 1
            self.code = f"BR{counter:03d}"
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.company.display_name} - {self.name}"

    @property
    def full_address(self):
        """Get full formatted address."""
        parts = [self.address, self.location]
        return ", ".join(filter(None, parts))

    def is_open_now(self):
        """Check if branch is currently open."""
        if not self.operating_hours:
            return True  # Assume open if no hours set
        
        from django.utils import timezone
        now = timezone.now()
        day_name = now.strftime('%A').lower()
        
        day_hours = self.operating_hours.get(day_name)
        if not day_hours or not day_hours.get('is_open', True):
            return False
        
        current_time = now.time()
        open_time = day_hours.get('open_time')
        close_time = day_hours.get('close_time')
        
        if open_time and close_time:
            from datetime import datetime
            open_dt = datetime.strptime(open_time, '%H:%M').time()
            close_dt = datetime.strptime(close_time, '%H:%M').time()
            return open_dt <= current_time <= close_dt
        
        return True

