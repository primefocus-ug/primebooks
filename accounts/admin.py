from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from .models import CustomUser,  UserSignature, Role, RoleHistory
# accounts/admin.py

from django.contrib import admin
from django.contrib.admin import AdminSite
from django.shortcuts import redirect
from django.urls import reverse

site_header = "PrimeBooks Administration"
site_title = "PrimeBooks Admin"

admin.site.register(Role)
class RestrictedAdminSite(AdminSite):
    """Admin site that only allows SaaS admins"""

    site_header = "PrimeBooks Administration"
    site_title = "PrimeBooks Admin"

    def has_permission(self, request):
        """
        Only SaaS admins can access Django admin
        """
        if not request.user.is_active:
            return False

        # Check is_saas_admin flag
        return getattr(request.user, 'is_saas_admin', False)

    def login(self, request, extra_context=None):
        """
        Redirect non-SaaS admins to regular login
        """
        if request.method == 'POST':
            # Try to authenticate
            from django.contrib.auth import authenticate
            username = request.POST.get('username')
            password = request.POST.get('password')

            user = authenticate(request, username=username, password=password)

            if user and not getattr(user, 'is_saas_admin', False):
                # Redirect to regular app instead
                return redirect(reverse('login'))

        return super().login(request, extra_context)


# Create custom admin site instance
admin_site = RestrictedAdminSite(name='admin')

# Register your models with the custom site
from .models import CustomUser, Role, UserSignature


class CustomUserAdmin(UserAdmin):
    list_display = ['email', 'get_primary_role', 'is_active']
    list_filter = ['groups__role__group__name', 'is_active']

    # ✅ ADD THIS — override everything
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name')}),
        (_('Permissions'), {
            'fields': (
                'is_active', 'is_staff', 'is_superuser',
                'groups', 'user_permissions',
            )
        }),
        (_('Important dates'), {
            'fields': ('last_login',),  # ✅ removed date_joined
        }),
    )

    # ✅ Add custom add_fieldsets (to avoid inheriting default ones)
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2'),
        }),
    )

    # ✅ OPTIONAL: ensure date_joined never shows in forms
    exclude = ('date_joined',)

    # ✅ Fix your custom role display
    def get_primary_role(self, obj):
        return obj.display_role

    get_primary_role.short_description = 'Primary Role'
    get_primary_role.admin_order_field = 'groups__role__priority'


@admin.register(Role, site=admin_site)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['group', 'company', 'priority', 'is_system_role', 'is_active']
    list_filter = ['is_system_role', 'is_active']


@admin.register(UserSignature)
class UserSignatureAdmin(admin.ModelAdmin):
    """Admin for managing user signatures and verification"""
    list_display = ("user", "is_verified", "verified_at", "verified_by", "created_at", "updated_at")
    list_filter = ("is_verified", "verified_at", "verified_by")
    search_fields = ("user__email", "user__username")
    readonly_fields = ("signature_hash", "created_at", "updated_at")


# Register CustomUser separately using UserAdmin override
admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(RoleHistory)