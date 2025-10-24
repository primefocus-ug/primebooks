from django.utils import timezone
from django.db import models
from inventory.models import Stock
from accounts.models import CustomUser


def notifications_context(request):
    notifications = []

    # Low stock items
    low_stock_items = Stock.objects.filter(quantity__lte=models.F('low_stock_threshold')).count()
    if low_stock_items > 0:
        notifications.append({
            'message': f'{low_stock_items} item{"s" if low_stock_items != 1 else ""} below reorder level',
            'icon': 'bi bi-exclamation-triangle',
            'url': '/inventory/stock/'
        })

    # New users registered in last 24h
    new_users_count = CustomUser.objects.filter(date_joined__gte=timezone.now() - timezone.timedelta(days=1)).count()
    if new_users_count > 0:
        notifications.append({
            'message': f'{new_users_count} new user{"s" if new_users_count != 1 else ""} registered',
            'icon': 'bi bi-person-plus',
            'url': '/accounts/users/'  # link to users list
        })

    # Example system update notification
    notifications.append({
        'message': 'System update available',
        'icon': 'bi bi-info-circle',
        'url': '/system/updates/'
    })

    return {
        'notifications': notifications,
        'notifications_count': len(notifications)
    }
