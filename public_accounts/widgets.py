from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta


class DashboardWidget:
    """Base class for dashboard widgets"""

    title = "Widget"
    template = "public_admin/widgets/base.html"

    def get_context(self, request):
        """Return context data for widget"""
        return {}


class UserStatsWidget(DashboardWidget):
    """Widget showing user statistics"""

    title = "User Statistics"
    template = "public_admin/widgets/user_stats.html"

    def get_context(self, request):
        from .models import PublicUser

        today = timezone.now().date()
        week_ago = today - timedelta(days=7)

        return {
            'total_users': PublicUser.objects.count(),
            'active_users': PublicUser.objects.filter(is_active=True).count(),
            'new_users_this_week': PublicUser.objects.filter(
                date_joined__date__gte=week_ago
            ).count(),
            'users_by_role': PublicUser.objects.values('role').annotate(
                count=Count('id')
            ),
        }


class RecentActivityWidget(DashboardWidget):
    """Widget showing recent activities"""

    title = "Recent Activities"
    template = "public_admin/widgets/recent_activities.html"

    def get_context(self, request):
        from .models import PublicUserActivity

        return {
            'activities': PublicUserActivity.objects.select_related('user')[:10],
        }


class SystemHealthWidget(DashboardWidget):
    """Widget showing system health metrics"""

    title = "System Health"
    template = "public_admin/widgets/system_health.html"

    def get_context(self, request):
        from .models import PublicUser, PasswordResetToken

        return {
            'locked_accounts': PublicUser.objects.filter(
                locked_until__gt=timezone.now()
            ).count(),
            'pending_password_resets': PasswordResetToken.objects.filter(
                is_used=False,
                expires_at__gt=timezone.now()
            ).count(),
            'unverified_emails': PublicUser.objects.filter(
                email_verified=False
            ).count(),
        }