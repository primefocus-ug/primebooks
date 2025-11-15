from django.db import models
from django.contrib.auth.hashers import make_password, check_password
import secrets


class PublicStaffUser(models.Model):
    """Simple staff user for public schema analytics access"""

    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)

    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    # Session token for authentication
    session_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'public_staff_users'
        verbose_name = 'Public Staff User'
        verbose_name_plural = 'Public Staff Users'

    def __str__(self):
        return self.username

    def set_password(self, raw_password):
        """Hash and set password"""
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        """Check password"""
        return check_password(raw_password, self.password)

    def generate_session_token(self):
        """Generate a new session token"""
        from django.utils import timezone
        from datetime import timedelta

        self.session_token = secrets.token_urlsafe(48)
        self.token_expires_at = timezone.now() + timedelta(days=7)
        self.save()
        return self.session_token

    def is_token_valid(self):
        """Check if session token is valid"""
        from django.utils import timezone

        if not self.session_token or not self.token_expires_at:
            return False
        return timezone.now() < self.token_expires_at

    def get_full_name(self):
        """Return full name"""
        return f"{self.first_name} {self.last_name}".strip() or self.username