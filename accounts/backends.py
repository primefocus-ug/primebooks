from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()


class RoleBasedAuthBackend(ModelBackend):
    """
    Custom authentication backend that respects role hierarchy
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """Standard authentication"""
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)

        try:
            user = User.objects.get(**{User.USERNAME_FIELD: username})
        except User.DoesNotExist:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None

    def has_perm(self, user_obj, perm, obj=None):
        """
        Check permissions through assigned roles
        """
        if not user_obj.is_active:
            return False

        # SaaS admin has all permissions
        if user_obj.is_saas_admin:
            return True

        # Check through groups/roles
        return super().has_perm(user_obj, perm, obj)

    def has_module_perms(self, user_obj, app_label):
        """
        Control admin access - only SaaS admins
        """
        if not user_obj.is_active:
            return False

        # Only SaaS admins can access Django admin
        if app_label == 'admin':
            return user_obj.is_saas_admin

        return user_obj.is_saas_admin or super().has_module_perms(user_obj, app_label)