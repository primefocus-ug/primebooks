from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from .models import CustomUser,  UserSignature, Role, RoleHistory


class CustomUserAdmin(UserAdmin):
    """Custom admin for managing users with additional fields"""
    model = CustomUser
    ordering = ("-date_joined",)
    list_display = (
        "email", "username", "user_type","first_name", "last_name", "is_active",
        "is_staff", "company_admin", "last_activity_at", "login_count","is_hidden", "saas_admin_badge"
    )
    list_filter = (
        "is_active", "is_staff", "company_admin",
        "user_type", "two_factor_enabled", "language"
    )
    search_fields = ("email", "username", "first_name", "last_name", "phone_number")

    # Make non-editable fields visible but read-only
    readonly_fields = ("password_changed_at","date_joined")

    # Fieldsets for viewing/editing users
    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        (_("Personal Info"), {"fields": ("first_name", "middle_name", "last_name", "phone_number", "avatar", "bio")}),
        (_("Permissions"), {"fields": ("user_type", "is_active", "is_staff", "is_superuser", "company_admin",
                                       "groups", "user_permissions")}),
        (_("Security"), {"fields": ("two_factor_enabled", "backup_codes", "failed_login_attempts", "locked_until")}),
        (_("Activity"), {"fields": ("last_login", "last_activity_at", "last_login_ip", "login_count", "password_changed_at")}),
        (_("Localization"), {"fields": ("timezone", "language")}),
        (_("Metadata"), {"fields": ("metadata",)}),
    )

    # Fields when creating new users
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "username", "password1", "password2", "user_type", "is_active", "is_staff"),
        }),
    )

    def saas_admin_badge(self, obj):
        if getattr(obj, 'is_saas_admin', False):
            return format_html(
                '<span class="badge" style="background-color: #dc3545; color: white;">SaaS Admin</span>'
            )
        return ''

    saas_admin_badge.short_description = 'SaaS Admin'

    def get_queryset(self, request):
        # Show hidden users in admin only if user is SaaS admin
        qs = super().get_queryset(request)
        if not getattr(request.user, 'is_saas_admin', False):
            qs = qs.filter(is_hidden=False)
        return qs


@admin.register(UserSignature)
class UserSignatureAdmin(admin.ModelAdmin):
    """Admin for managing user signatures and verification"""
    list_display = ("user", "is_verified", "verified_at", "verified_by", "created_at", "updated_at")
    list_filter = ("is_verified", "verified_at", "verified_by")
    search_fields = ("user__email", "user__username")
    readonly_fields = ("signature_hash", "created_at", "updated_at")


# Register CustomUser separately using UserAdmin override
admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(Role)
admin.site.register(RoleHistory)