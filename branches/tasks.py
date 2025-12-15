from celery import shared_task
from django.utils import timezone
from stores.models import Store
import logging

logger = logging.getLogger(__name__)


@shared_task
def send_periodic_analytics_update():
    """Send periodic analytics updates to all active stores."""
    from sales.models import Sale
    from django.db.models import Sum, Count
    from datetime import timedelta

    stores = Store.objects.filter(is_active=True).select_related('company')

    for store in stores:
        try:
            # Calculate current metrics
            today = timezone.now().date()

            today_metrics = Sale.objects.filter(
                store=store,
                created_at__date=today,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                revenue=Sum('total_amount'),
                count=Count('id')
            )

            update_data = {
                'store_id': store.id,
                'store_name': store.name,
                'metrics': {
                    'today_revenue': float(today_metrics['revenue'] or 0),
                    'today_sales': today_metrics['count'] or 0,
                },
                'timestamp': timezone.now().isoformat()
            }

            # Use the websocket notifier
            from .utils import websocket_notifier
            websocket_notifier.send_store_update(
                store.id,
                update_data,
                'periodic_update'
            )

        except Exception as e:
            logger.error(f'Periodic update failed for store {store.id}: {e}')


@shared_task
def send_company_summary_update(company_id):
    """Send company-wide summary update."""
    try:
        from company.models import Company
        from sales.models import Sale
        from django.db.models import Sum, Count
        from datetime import timedelta

        company = Company.objects.get(company_id=company_id)
        stores = Store.objects.filter(company=company, is_active=True)

        today = timezone.now().date()
        store_ids = stores.values_list('id', flat=True)

        today_metrics = Sale.objects.filter(
            store_id__in=store_ids,
            created_at__date=today,
            is_voided=False,
            status__in=['COMPLETED', 'PAID']
        ).aggregate(
            revenue=Sum('total_amount'),
            count=Count('id')
        )

        update_data = {
            'company_id': company_id,
            'company_name': company.name,
            'metrics': {
                'today_revenue': float(today_metrics['revenue'] or 0),
                'today_sales': today_metrics['count'] or 0,
                'active_stores': stores.count()
            },
            'timestamp': timezone.now().isoformat()
        }

        from .utils import websocket_notifier
        websocket_notifier.send_company_update(
            company_id,
            update_data,
            'company_summary'
        )

    except Exception as e:
        logger.error(f'Company summary update failed for company {company_id}: {e}')

