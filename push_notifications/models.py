from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
import uuid


class PushNotificationType(models.Model):
    """
    Defines a category of push notification e.g. 'sale_created', 'low_stock'.
    Admin creates these once; they are available to all tenants.
    """
    code = models.CharField(
        max_length=100,
        unique=True,
        help_text=_("Unique identifier e.g. 'sale_created', 'low_stock'")
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=50,
        blank=True,
        default='bell',
        help_text=_("Icon name for the notification")
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Push Notification Type")
        verbose_name_plural = _("Push Notification Types")
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class RoleNotificationDefault(models.Model):
    """
    Defines which PushNotificationTypes a Role receives by default.
    When a user is assigned this role, these types are auto-applied.
    """
    role = models.ForeignKey(
        'accounts.Role',
        on_delete=models.CASCADE,
        related_name='push_notification_defaults'
    )
    notification_type = models.ForeignKey(
        PushNotificationType,
        on_delete=models.CASCADE,
        related_name='role_defaults'
    )

    class Meta:
        unique_together = ['role', 'notification_type']
        verbose_name = _("Role Notification Default")
        verbose_name_plural = _("Role Notification Defaults")

    def __str__(self):
        return f"{self.role} → {self.notification_type.name}"


class UserPushPreference(models.Model):
    """
    Per-user override of which push notification types they receive.
    Auto-created from role defaults; admin can then toggle individual entries.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='push_preferences'
    )
    notification_type = models.ForeignKey(
        PushNotificationType,
        on_delete=models.CASCADE,
        related_name='user_preferences'
    )
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'notification_type']
        verbose_name = _("User Push Preference")
        verbose_name_plural = _("User Push Preferences")

    def __str__(self):
        status = "✓" if self.enabled else "✗"
        return f"{status} {self.user} → {self.notification_type.name}"


class PushSubscription(models.Model):
    """
    Stores the browser push subscription for a user.
    Now uses FCM tokens instead of raw VAPID keys.
    Created when user grants notification permission in their browser.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='push_subscriptions'
    )

    # ── FCM token (replaces endpoint + p256dh + auth) ──────────────────────────
    # This is the registration token returned by getToken() in the Firebase SDK.
    fcm_token = models.TextField(unique=True, blank=True, default='')

    # ── Legacy Web Push fields — kept so old subscriptions still exist in DB ───
    # New subscriptions will leave these blank.
    endpoint = models.TextField(unique=True, blank=True, default='')
    p256dh = models.TextField(blank=True, default='')
    auth = models.TextField(blank=True, default='')

    user_agent = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Push Subscription")
        verbose_name_plural = _("Push Subscriptions")
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        identifier = self.fcm_token[:60] if self.fcm_token else self.endpoint[:60]
        return f"{self.user} - {identifier}..."