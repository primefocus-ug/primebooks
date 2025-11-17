from django.utils.translation import gettext_lazy as _
from public_accounts.admin_site import public_admin, PublicModelAdmin
from .models import PublicUser, PasswordResetToken, PublicUserActivity
from .forms import PublicUserCreationForm, PublicUserChangeForm


class PublicUserAdmin(PublicModelAdmin):
    """Admin interface for PublicUser"""

    form_class = PublicUserChangeForm
    add_form_class = PublicUserCreationForm

    list_display = [
        'identifier', 'email', 'username', 'get_full_name', 'role',
        'is_active', 'is_staff', 'date_joined'
    ]
    list_filter = ['role', 'is_active', 'is_staff', 'is_admin', 'date_joined']
    search_fields = ['identifier', 'email', 'username', 'first_name', 'last_name']
    ordering = ['-date_joined']
    readonly_fields = ['identifier', 'date_joined', 'last_login', 'password_changed_at',
                       'last_login_ip', 'last_activity']

    fieldsets = (
        (_('Login Information'), {
            'fields': ('identifier', 'email')
        }),
        (_('Personal Information'), {
            'fields': ('username', 'first_name', 'last_name', 'phone', 'avatar', 'bio')
        }),
        (_('Permissions & Role'), {
            'fields': (
                'role', 'is_active', 'is_staff', 'is_admin',
                'can_manage_seo', 'can_manage_blog', 'can_manage_support',
                'can_manage_companies', 'can_view_analytics'
            ),
        }),
        (_('Security'), {
            'fields': (
                'email_verified', 'force_password_change', 'password_changed_at',
                'failed_login_attempts', 'locked_until', 'last_login_ip'
            ),
            'classes': ('collapse',),
        }),
        (_('Important Dates'), {
            'fields': ('last_login', 'date_joined', 'last_activity'),
            'classes': ('collapse',),
        }),
    )

    def get_form_class(self):
        """Return appropriate form class"""
        if hasattr(self, '_adding'):
            return self.add_form_class
        return self.form_class

    def add_view(self, request):
        """Override to use add_form_class"""
        self._adding = True
        response = super().add_view(request)
        delattr(self, '_adding')
        return response


class PasswordResetTokenAdmin(PublicModelAdmin):
    """Admin interface for PasswordResetToken"""

    list_display = ['user', 'created_at', 'expires_at', 'is_used', 'used_at', 'ip_address']
    list_filter = ['is_used', 'created_at', 'expires_at']
    search_fields = ['user__identifier', 'user__email', 'token']
    readonly_fields = ['token', 'created_at', 'used_at', 'user', 'expires_at', 'ip_address']
    ordering = ['-created_at']

    has_add_permission_flag = False
    has_change_permission_flag = False


class PublicUserActivityAdmin(PublicModelAdmin):
    """Admin interface for PublicUserActivity"""

    list_display = ['user', 'action', 'app_name', 'model_name', 'timestamp', 'ip_address']
    list_filter = ['action', 'app_name', 'timestamp']
    search_fields = ['user__identifier', 'user__email', 'description', 'object_id']
    readonly_fields = ['user', 'action', 'app_name', 'model_name', 'object_id',
                       'description', 'ip_address', 'user_agent', 'timestamp']
    ordering = ['-timestamp']
    list_per_page = 50

    has_add_permission_flag = False
    has_change_permission_flag = False


# Register models with public admin
public_admin.register(PublicUser, PublicUserAdmin, app_label='public_accounts')
public_admin.register(PasswordResetToken, PasswordResetTokenAdmin, app_label='public_accounts')
public_admin.register(PublicUserActivity, PublicUserActivityAdmin, app_label='public_accounts')
