from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from .models import Notification, NotificationPreference


class NotificationMixin(LoginRequiredMixin):
    """
    Mixin to add notification context to views
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.user.is_authenticated:
            context['unread_notifications_count'] = Notification.objects.filter(
                recipient=self.request.user,
                is_read=False,
                is_dismissed=False
            ).count()

            context['has_unread_notifications'] = context['unread_notifications_count'] > 0

        return context


class UserNotificationsMixin:
    """
    Mixin to filter notifications for the current user
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        if hasattr(self.request, 'user') and self.request.user.is_authenticated:
            return queryset.filter(recipient=self.request.user)
        return queryset.none()

