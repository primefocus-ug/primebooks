from public_router.models import TenantSignupRequest
from django.utils import timezone
from datetime import timedelta


def get_signup_stats():
    """Get signup statistics for dashboard"""
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    stats = {
        'pending': TenantSignupRequest.objects.filter(status='PENDING').count(),
        'processing': TenantSignupRequest.objects.filter(status='PROCESSING').count(),
        'completed_today': TenantSignupRequest.objects.filter(
            status='COMPLETED',
            completed_at__date=today
        ).count(),
        'completed_week': TenantSignupRequest.objects.filter(
            status='COMPLETED',
            completed_at__date__gte=week_ago
        ).count(),
        'completed_month': TenantSignupRequest.objects.filter(
            status='COMPLETED',
            completed_at__date__gte=month_ago
        ).count(),
        'failed': TenantSignupRequest.objects.filter(status='FAILED').count(),
        'total': TenantSignupRequest.objects.count(),
    }

    # Recent signups
    stats['recent'] = TenantSignupRequest.objects.select_related(
        'approval_workflow'
    ).order_by('-created_at')[:5]

    return stats
