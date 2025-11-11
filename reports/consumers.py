from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


class ReportDashboardConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for real-time dashboard updates
    """

    async def connect(self):
        self.user = self.scope['user']

        if not self.user.is_authenticated:
            await self.close()
            return

        # Join user-specific group for personalized updates
        self.user_group_name = f'user_{self.user.id}_reports'
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )

        # Join company-wide report group - FIX: Check company ID asynchronously
        company_id = await self.get_user_company_id()
        if company_id:
            self.company_group_name = f'company_{company_id}_reports'
            await self.channel_layer.group_add(
                self.company_group_name,
                self.channel_name
            )

        await self.accept()

        # Send initial dashboard stats
        await self.send_dashboard_stats()

        logger.info(f"WebSocket connected for user {self.user.id}")

    # Add this new helper method
    @database_sync_to_async
    def get_user_company_id(self):
        """Get user's company ID safely"""
        try:
            if hasattr(self.user, 'company') and self.user.company:
                return self.user.company.company_id
        except Exception:
            pass
        return None

    async def disconnect(self, close_code):
        # Leave groups
        await self.channel_layer.group_discard(
            self.user_group_name,
            self.channel_name
        )

        if hasattr(self, 'company_group_name'):
            await self.channel_layer.group_discard(
                self.company_group_name,
                self.channel_name
            )

        logger.info(f"WebSocket disconnected for user {self.user.id}")

    async def receive_json(self, content):
        """Handle incoming messages from client"""
        message_type = content.get('type')

        if message_type == 'request_stats':
            await self.send_dashboard_stats()

        elif message_type == 'request_alerts':
            await self.send_alerts()

        elif message_type == 'subscribe_report':
            report_id = content.get('report_id')
            await self.subscribe_to_report(report_id)

        elif message_type == 'ping':
            await self.send_json({'type': 'pong'})

    async def send_dashboard_stats(self):
        """Send current dashboard statistics"""
        stats = await self.get_dashboard_stats()

        await self.send_json({
            'type': 'dashboard_stats',
            'data': stats,
            'timestamp': timezone.now().isoformat()
        })

    async def send_alerts(self):
        """Send stock and compliance alerts"""
        alerts = await self.get_alerts()

        await self.send_json({
            'type': 'alerts',
            'data': alerts,
            'timestamp': timezone.now().isoformat()
        })

    async def subscribe_to_report(self, report_id):
        """Subscribe to updates for a specific report generation"""
        group_name = f'report_{report_id}_progress'
        await self.channel_layer.group_add(
            group_name,
            self.channel_name
        )

        await self.send_json({
            'type': 'subscribed',
            'report_id': report_id
        })

    # Handler methods for group messages
    async def report_progress(self, event):
        """Send report generation progress"""
        await self.send_json({
            'type': 'report_progress',
            'report_id': event['report_id'],
            'progress': event['progress'],
            'message': event.get('message', ''),
            'status': event.get('status', 'processing')
        })

    async def report_complete(self, event):
        """Notify report generation completion"""
        await self.send_json({
            'type': 'report_complete',
            'report_id': event['report_id'],
            'generated_report_id': event['generated_report_id'],
            'download_url': event.get('download_url', ''),
            'file_size': event.get('file_size', 0),
            'row_count': event.get('row_count', 0)
        })

    async def report_failed(self, event):
        """Notify report generation failure"""
        await self.send_json({
            'type': 'report_failed',
            'report_id': event['report_id'],
            'error': event.get('error', 'Unknown error occurred')
        })

    async def stats_update(self, event):
        """Broadcast stats update"""
        await self.send_json({
            'type': 'stats_update',
            'data': event['stats'],
            'timestamp': event['timestamp']
        })

    async def alert_update(self, event):
        """Broadcast new alert"""
        await self.send_json({
            'type': 'alert',
            'alert_type': event['alert_type'],
            'message': event['message'],
            'severity': event.get('severity', 'info'),
            'data': event.get('data', {})
        })

    @database_sync_to_async
    def get_dashboard_stats(self):
        """Get current dashboard statistics"""
        from sales.models import Sale
        from inventory.models import Stock
        from invoices.models import Invoice
        from stores.models import Store
        from django.db.models import Sum, Count, F

        # Check cache first
        cache_key = f'dashboard_stats_{self.user.id}'
        cached_stats = cache.get(cache_key)
        if cached_stats:
            return cached_stats

        # Get user's accessible stores
        if self.user.is_superuser or self.user.primary_role and user.primary_role.priority >= 90:
            stores = Store.objects.filter(is_active=True)
        else:
            stores = self.user.stores.filter(is_active=True)

        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        # Sales statistics
        stats = {
            'sales_today': float(Sale.objects.filter(
                store__in=stores,
                created_at__date=today,
                is_completed=True
            ).aggregate(total=Sum('total_amount'))['total'] or 0),

            'sales_week': float(Sale.objects.filter(
                store__in=stores,
                created_at__date__gte=week_ago,
                is_completed=True
            ).aggregate(total=Sum('total_amount'))['total'] or 0),

            'sales_month': float(Sale.objects.filter(
                store__in=stores,
                created_at__date__gte=month_ago,
                is_completed=True
            ).aggregate(total=Sum('total_amount'))['total'] or 0),

            'transactions_today': Sale.objects.filter(
                store__in=stores,
                created_at__date=today,
                is_completed=True
            ).count(),

            # Inventory alerts
            'low_stock_count': Stock.objects.filter(
                store__in=stores,
                quantity__lte=F('low_stock_threshold'),
                quantity__gt=0
            ).count(),

            'out_of_stock_count': Stock.objects.filter(
                store__in=stores,
                quantity=0
            ).count(),

            # Invoice statistics
            'pending_invoices': Invoice.objects.filter(
                store__in=stores,
                status__in=['SENT', 'PARTIALLY_PAID']
            ).count(),

            'overdue_invoices': Invoice.objects.filter(
                store__in=stores,
                status__in=['SENT', 'PARTIALLY_PAID'],
                due_date__lt=today
            ).count(),

            # EFRIS compliance
            'pending_fiscalization': Sale.objects.filter(
                store__in=stores,
                is_completed=True,
                is_fiscalized=False,
                created_at__date__gte=today - timedelta(days=7)
            ).count(),
        }

        # Cache for 2 minutes
        cache.set(cache_key, stats, 120)

        return stats

    @database_sync_to_async
    def get_alerts(self):
        """Get current alerts"""
        from inventory.models import Stock
        from sales.models import Sale
        from stores.models import Store
        from django.db.models import F

        alerts = []

        # Get user's accessible stores
        if self.user.is_superuser or self.user.primary_role and user.primary_role.priority >= 90:
            stores = Store.objects.filter(is_active=True)
        else:
            stores = self.user.stores.filter(is_active=True)

        # Low stock alerts
        low_stock = Stock.objects.filter(
            store__in=stores,
            quantity__lte=F('low_stock_threshold'),
            quantity__gt=0
        ).select_related('product', 'store')[:10]

        for stock in low_stock:
            alerts.append({
                'type': 'low_stock',
                'severity': 'warning',
                'message': f'{stock.product.name} is low in stock at {stock.store.name}',
                'product_id': stock.product.id,
                'store_id': stock.store.id,
                'quantity': stock.quantity,
                'threshold': stock.low_stock_threshold
            })

        # Out of stock alerts
        out_of_stock = Stock.objects.filter(
            store__in=stores,
            quantity=0
        ).select_related('product', 'store')[:10]

        for stock in out_of_stock:
            alerts.append({
                'type': 'out_of_stock',
                'severity': 'critical',
                'message': f'{stock.product.name} is out of stock at {stock.store.name}',
                'product_id': stock.product.id,
                'store_id': stock.store.id
            })

        # Pending fiscalization alerts
        today = timezone.now().date()
        pending_fiscal = Sale.objects.filter(
            store__in=stores,
            is_completed=True,
            is_fiscalized=False,
            created_at__date__gte=today - timedelta(days=7)
        ).count()

        if pending_fiscal > 0:
            alerts.append({
                'type': 'efris_pending',
                'severity': 'warning',
                'message': f'{pending_fiscal} sales pending EFRIS fiscalization',
                'count': pending_fiscal
            })

        # Failed fiscalization alerts
        failed_fiscal = Sale.objects.filter(
            store__in=stores,
            is_completed=True,
            fiscalization_failed=True,
            created_at__date__gte=today - timedelta(days=7)
        ).count()

        if failed_fiscal > 0:
            alerts.append({
                'type': 'efris_failed',
                'severity': 'critical',
                'message': f'{failed_fiscal} sales failed EFRIS fiscalization',
                'count': failed_fiscal
            })

        return alerts


class ReportGenerationConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for tracking report generation progress
    """

    async def connect(self):
        self.user = self.scope['user']
        self.report_id = self.scope['url_route']['kwargs'].get('report_id')

        if not self.user.is_authenticated:
            await self.close()
            return

        # Verify user has access to this report
        has_access = await self.verify_report_access()
        if not has_access:
            await self.close()
            return

        # Join report-specific group
        self.group_name = f'report_{self.report_id}_generation'
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

        # Send current status
        await self.send_report_status()

        logger.info(f"Report generation WebSocket connected: Report {self.report_id}, User {self.user.id}")

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def receive_json(self, content):
        """Handle incoming messages"""
        message_type = content.get('type')

        if message_type == 'request_status':
            await self.send_report_status()

        elif message_type == 'cancel_generation':
            await self.cancel_report_generation()

    async def generation_started(self, event):
        """Notify that report generation has started"""
        await self.send_json({
            'type': 'started',
            'message': 'Report generation started',
            'timestamp': event.get('timestamp')
        })

    async def generation_progress(self, event):
        """Send progress update"""
        await self.send_json({
            'type': 'progress',
            'progress': event['progress'],
            'message': event.get('message', ''),
            'current_step': event.get('current_step', ''),
            'total_steps': event.get('total_steps', 0)
        })

    async def generation_complete(self, event):
        """Notify completion"""
        await self.send_json({
            'type': 'complete',
            'generated_report_id': event['generated_report_id'],
            'download_url': event['download_url'],
            'file_size': event.get('file_size', 0),
            'row_count': event.get('row_count', 0),
            'generation_time': event.get('generation_time', 0)
        })

    async def generation_failed(self, event):
        """Notify failure"""
        await self.send_json({
            'type': 'failed',
            'error': event['error'],
            'error_details': event.get('error_details', '')
        })

    @database_sync_to_async
    def verify_report_access(self):
        """Verify user has access to this report"""
        from ..models import GeneratedReport
        from django.db.models import Q

        try:
            report = GeneratedReport.objects.get(id=self.report_id)

            # Check if user is owner or has access
            if report.generated_by == self.user:
                return True

            if self.user.is_superuser or self.user.primary_role and user.primary_role.priority >= 90:
                return True

            # Check if report is shared
            if report.report.is_shared:
                return True

            return False
        except GeneratedReport.DoesNotExist:
            return False

    @database_sync_to_async
    def send_report_status(self):
        """Send current report status"""
        from ..models import GeneratedReport

        try:
            report = GeneratedReport.objects.get(id=self.report_id)

            status_data = {
                'type': 'status',
                'status': report.status,
                'progress': report.progress,
                'error_message': report.error_message
            }

            if report.status == 'COMPLETED':
                status_data.update({
                    'download_url': f'/reports/download/{report.id}/',
                    'file_size': report.file_size,
                    'row_count': report.row_count
                })

            return status_data
        except GeneratedReport.DoesNotExist:
            return {
                'type': 'error',
                'error': 'Report not found'
            }

    @database_sync_to_async
    def cancel_report_generation(self):
        """Cancel ongoing report generation"""
        from ..models import GeneratedReport
        from celery import current_app

        try:
            report = GeneratedReport.objects.get(id=self.report_id)

            if report.status in ['PENDING', 'PROCESSING']:
                # Revoke celery task if exists
                if report.task_id:
                    current_app.control.revoke(report.task_id, terminate=True)

                report.status = 'CANCELLED'
                report.error_message = 'Cancelled by user'
                report.save()

                return {'success': True, 'message': 'Report generation cancelled'}

            return {'success': False, 'message': 'Report cannot be cancelled'}
        except GeneratedReport.DoesNotExist:
            return {'success': False, 'message': 'Report not found'}


# Utility function to broadcast updates
async def broadcast_dashboard_update(company_id, stats):
    """Broadcast dashboard stats update to all connected clients"""
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    group_name = f'company_{company_id}_reports'

    await channel_layer.group_send(
        group_name,
        {
            'type': 'stats_update',
            'stats': stats,
            'timestamp': timezone.now().isoformat()
        }
    )


async def broadcast_alert(company_id, alert_type, message, severity='info', data=None):
    """Broadcast alert to all connected clients"""
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    group_name = f'company_{company_id}_reports'

    await channel_layer.group_send(
        group_name,
        {
            'type': 'alert_update',
            'alert_type': alert_type,
            'message': message,
            'severity': severity,
            'data': data or {}
        }
    )


async def send_report_progress(report_id, progress, message='', status='processing'):
    """Send report generation progress update"""
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    group_name = f'report_{report_id}_progress'

    await channel_layer.group_send(
        group_name,
        {
            'type': 'report_progress',
            'report_id': report_id,
            'progress': progress,
            'message': message,
            'status': status
        }
    )


async def send_report_complete(report_id, generated_report_id, download_url, file_size, row_count):
    """Notify report generation completion"""
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    group_name = f'report_{report_id}_progress'

    await channel_layer.group_send(
        group_name,
        {
            'type': 'report_complete',
            'report_id': report_id,
            'generated_report_id': generated_report_id,
            'download_url': download_url,
            'file_size': file_size,
            'row_count': row_count
        }
    )


async def send_report_failed(report_id, error):
    """Notify report generation failure"""
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    group_name = f'report_{report_id}_progress'

    await channel_layer.group_send(
        group_name,
        {
            'type': 'report_failed',
            'report_id': report_id,
            'error': error
        }
    )