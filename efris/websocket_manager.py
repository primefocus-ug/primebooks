import json
import logging
from typing import Dict, Any, List, Optional
from django.utils import timezone
from django.core.cache import cache
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EFRISWebSocketEvent:
    """Data class for EFRIS WebSocket events"""
    event_type: str
    data: Dict[str, Any]
    company_id: int
    timestamp: str = field(default_factory=lambda: timezone.now().isoformat())
    event_category: str = 'general'
    priority: str = 'normal'
    metadata: Dict[str, Any] = field(default_factory=dict)


class EFRISWebSocketManager:
    """Centralized manager for EFRIS WebSocket operations"""

    def __init__(self):
        self.channel_layer = get_channel_layer()

    def broadcast_event(self, event: EFRISWebSocketEvent) -> bool:
        """Broadcast an EFRIS event to all connected clients for a company"""
        if not self.channel_layer:
            logger.warning("No channel layer configured")
            return False

        try:
            group_name = f"efris_company_{event.company_id}"

            broadcast_data = {
                'type': 'efris_event',
                'event_type': event.event_type,
                'event_category': event.event_category,
                'data': event.data,
                'timestamp': event.timestamp,
                'company_id': event.company_id,
                'priority': event.priority,
                'metadata': event.metadata
            }

            async_to_sync(self.channel_layer.group_send)(group_name, broadcast_data)

            # Track metrics
            self._track_broadcast_metrics(event)

            logger.debug(f"Broadcasted EFRIS event '{event.event_type}' to company {event.company_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to broadcast EFRIS event: {e}")
            return False

    def send_notification(self, company_id: int, title: str, message: str,
                          notification_type: str = 'info', priority: str = 'normal',
                          metadata: Dict[str, Any] = None) -> bool:
        """Send a notification via WebSocket"""

        event = EFRISWebSocketEvent(
            event_type='notification',
            data={
                'title': title,
                'message': message,
                'type': notification_type,
                'priority': priority,
                'metadata': metadata or {}
            },
            company_id=company_id,
            event_category='notification',
            priority=priority
        )

        return self.broadcast_event(event)

    def broadcast_invoice_status(self, company_id: int, invoice_id: int,
                                 invoice_number: str, status: str,
                                 message: str = None, **kwargs) -> bool:
        """Broadcast invoice fiscalization status update"""

        event_type_map = {
            'started': 'invoice_fiscalization_started',
            'completed': 'invoice_fiscalization_completed',
            'failed': 'invoice_fiscalization_failed',
            'error': 'invoice_fiscalization_error'
        }

        event_type = event_type_map.get(status, f'invoice_fiscalization_{status}')

        event_data = {
            'invoice_id': invoice_id,
            'invoice_number': invoice_number,
            'status': status,
            **kwargs
        }

        if message:
            event_data['message'] = message

        event = EFRISWebSocketEvent(
            event_type=event_type,
            data=event_data,
            company_id=company_id,
            event_category='invoice'
        )

        return self.broadcast_event(event)

    def broadcast_product_status(self, company_id: int, product_ids: List[int],
                                 status: str, message: str = None, **kwargs) -> bool:
        """Broadcast product upload/update status"""

        event_type_map = {
            'started': 'product_upload_started',
            'completed': 'product_upload_completed',
            'failed': 'product_upload_failed',
            'error': 'product_upload_error'
        }

        event_type = event_type_map.get(status, f'product_upload_{status}')

        event_data = {
            'product_ids': product_ids,
            'product_count': len(product_ids),
            'status': status,
            **kwargs
        }

        if message:
            event_data['message'] = message

        event = EFRISWebSocketEvent(
            event_type=event_type,
            data=event_data,
            company_id=company_id,
            event_category='product'
        )

        return self.broadcast_event(event)

    def broadcast_queue_status(self, company_id: int, queue_item_id: int,
                               sync_type: str, object_id: int, status: str,
                               message: str = None) -> bool:
        """Broadcast queue processing status"""

        event_type_map = {
            'processing': 'queue_item_processing',
            'completed': 'queue_item_completed',
            'failed': 'queue_item_failed',
            'retry': 'queue_item_retry'
        }

        event_type = event_type_map.get(status, f'queue_item_{status}')

        event_data = {
            'queue_item_id': queue_item_id,
            'sync_type': sync_type,
            'object_id': object_id,
            'status': status
        }

        if message:
            event_data['message'] = message

        event = EFRISWebSocketEvent(
            event_type=event_type,
            data=event_data,
            company_id=company_id,
            event_category='queue'
        )

        return self.broadcast_event(event)

    def broadcast_health_status(self, company_id: int, health_data: Dict[str, Any]) -> bool:
        """Broadcast health check results"""

        event = EFRISWebSocketEvent(
            event_type='health_check_completed',
            data=health_data,
            company_id=company_id,
            event_category='system'
        )

        return self.broadcast_event(event)

    def get_active_connections(self, company_id: int) -> List[Dict[str, Any]]:
        """Get active WebSocket connections for a company"""
        try:
            cache_key = f"efris_ws_connections_{company_id}"
            connections = cache.get(cache_key, [])

            # Clean up expired connections
            current_time = timezone.now()
            active_connections = []

            for conn in connections:
                try:
                    connected_at = timezone.datetime.fromisoformat(
                        conn['connected_at'].replace('Z', '+00:00')
                    )
                    # Consider connection active for 1 hour
                    if (current_time - connected_at).total_seconds() < 3600:
                        active_connections.append(conn)
                except (KeyError, ValueError, TypeError):
                    continue

            # Update cache
            cache.set(cache_key, active_connections, timeout=3600)
            return active_connections

        except Exception as e:
            logger.error(f"Error getting active connections: {e}")
            return []

    def get_connection_stats(self, company_id: int) -> Dict[str, Any]:
        """Get WebSocket connection statistics"""
        try:
            connections = self.get_active_connections(company_id)

            stats = {
                'active_connections': len(connections),
                'unique_users': len(set(conn.get('user_id') for conn in connections if conn.get('user_id'))),
                'connections_by_user': {},
                'oldest_connection': None,
                'newest_connection': None
            }

            if connections:
                # Group by user
                for conn in connections:
                    user_id = conn.get('user_id')
                    if user_id:
                        if user_id not in stats['connections_by_user']:
                            stats['connections_by_user'][user_id] = 0
                        stats['connections_by_user'][user_id] += 1

                # Find oldest and newest connections
                connection_times = [conn['connected_at'] for conn in connections if conn.get('connected_at')]
                if connection_times:
                    stats['oldest_connection'] = min(connection_times)
                    stats['newest_connection'] = max(connection_times)

            return stats

        except Exception as e:
            logger.error(f"Error getting connection stats: {e}")
            return {'active_connections': 0, 'error': str(e)}

    def _track_broadcast_metrics(self, event: EFRISWebSocketEvent):
        """Track broadcast metrics for monitoring"""
        try:
            # Track by event type
            event_key = f"efris_broadcasts_{event.event_type}"
            cache.set(event_key, cache.get(event_key, 0) + 1, timeout=3600)

            # Track by company
            company_key = f"efris_company_broadcasts_{event.company_id}"
            cache.set(company_key, cache.get(company_key, 0) + 1, timeout=3600)

            # Track by category
            category_key = f"efris_category_broadcasts_{event.event_category}"
            cache.set(category_key, cache.get(category_key, 0) + 1, timeout=3600)

            # Track hourly statistics
            hour_key = f"efris_broadcasts_hour_{timezone.now().strftime('%Y%m%d_%H')}"
            cache.set(hour_key, cache.get(hour_key, 0) + 1, timeout=3600)

        except Exception as e:
            logger.error(f"Error tracking broadcast metrics: {e}")



# Global WebSocket manager instance
websocket_manager = EFRISWebSocketManager()

