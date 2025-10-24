import json
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


def broadcast_to_company(company_id: int, event_type: str, data: Dict[str, Any],
                         event_category: str = 'general') -> bool:
    """Enhanced broadcast function with error handling and monitoring"""
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("No channel layer configured for EFRIS WebSocket broadcasting")
            return False

        # Add metadata
        broadcast_data = {
            'type': 'efris_event',
            'event_type': event_type,
            'event_category': event_category,
            'data': data,
            'timestamp': timezone.now().isoformat(),
            'company_id': company_id
        }

        # Send to company group
        async_to_sync(channel_layer.group_send)(
            f"efris_company_{company_id}",
            broadcast_data
        )

        # Track broadcast for monitoring
        track_broadcast_metrics(company_id, event_type, event_category)

        logger.debug(f"Broadcasted EFRIS event '{event_type}' to company {company_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to broadcast EFRIS event: {e}")
        return False


def track_broadcast_metrics(company_id: int, event_type: str, event_category: str):
    """Track broadcast metrics for monitoring"""
    try:
        from django.core.cache import cache

        # Track by event type
        event_key = f"efris_broadcasts_{event_type}"
        event_count = cache.get(event_key, 0) + 1
        cache.set(event_key, event_count, timeout=3600)

        # Track by company
        company_key = f"efris_company_broadcasts_{company_id}"
        company_count = cache.get(company_key, 0) + 1
        cache.set(company_key, company_count, timeout=3600)

        # Track by category
        category_key = f"efris_category_broadcasts_{event_category}"
        category_count = cache.get(category_key, 0) + 1
        cache.set(category_key, category_count, timeout=3600)

    except Exception as e:
        logger.error(f"Error tracking broadcast metrics: {e}")


def get_active_connections(company_id: int) -> List[Dict[str, Any]]:
    """Get list of active WebSocket connections for a company"""
    try:
        from django.core.cache import cache

        cache_key = f"efris_ws_connections_{company_id}"
        connections = cache.get(cache_key, [])

        # Filter out expired connections (optional cleanup)
        current_time = timezone.now()
        active_connections = []

        for conn in connections:
            try:
                connected_at = timezone.datetime.fromisoformat(
                    conn['connected_at'].replace('Z', '+00:00')
                )
                # Connection considered active for 1 hour without heartbeat
                if (current_time - connected_at).total_seconds() < 3600:
                    active_connections.append(conn)
            except (KeyError, ValueError):
                continue

        # Update cache with cleaned connections
        cache.set(cache_key, active_connections, timeout=3600)

        return active_connections

    except Exception as e:
        logger.error(f"Error getting active connections: {e}")
        return []


def send_efris_notification_realtime(company_id: int, title: str, message: str,
                                     notification_type: str = 'info',
                                     priority: str = 'normal',
                                     metadata: Dict[str, Any] = None) -> bool:
    """Send real-time notification via WebSocket"""

    notification_data = {
        'title': title,
        'message': message,
        'type': notification_type,
        'priority': priority,
        'metadata': metadata or {},
        'timestamp': timezone.now().isoformat()
    }

    return broadcast_to_company(
        company_id,
        'notification',
        notification_data,
        'notification'
    )