from celery import shared_task
from django.utils import timezone
from .utils import websocket_notifier
from stores.models import Store

@shared_task
def send_periodic_analytics_update():
    '''Send periodic analytics updates to all active branches.'''
    branches = Store.objects.filter(is_active=True)

    for branch in branches:
        try:
            # Calculate current metrics
            stores = branch.stores.filter(is_active=True)
            # ... calculate metrics ...

            update_data = {
                'branch_id': branch.id,
                'metrics': {
                    # ... your metrics
                },
                'timestamp': timezone.now().isoformat()
            }

            websocket_notifier.send_branch_update(
                branch.id,
                update_data,
                'periodic_update'
            )

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Periodic update failed for branch {branch.id}: {e}')
