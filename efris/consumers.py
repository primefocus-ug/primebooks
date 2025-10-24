import json
import logging
from typing import Dict, Any
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.exceptions import DenyConnection
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from asgiref.sync import sync_to_async
from django.core.cache import cache

logger = logging.getLogger(__name__)


class EFRISConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time EFRIS updates"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.company_id = None
        self.company_group_name = None
        self.user = None
        self.connected_at = None
        self.last_heartbeat = None

    async def connect(self):
        """Handle WebSocket connection"""
        try:
            # Get company_id from URL route
            self.company_id = self.scope['url_route']['kwargs']['company_id']
            self.user = self.scope.get('user')

            # Check authentication
            if isinstance(self.user, AnonymousUser):
                logger.warning(f"Anonymous user attempted EFRIS WebSocket connection for company {self.company_id}")
                await self.close(code=4001)  # Custom code for auth failure
                return

            # Verify user has access to this company
            has_access = await self.verify_company_access()
            if not has_access:
                logger.warning(f"User {self.user.id} denied access to company {self.company_id}")
                await self.close(code=4003)  # Custom code for access denied
                return

            # Join company group
            self.company_group_name = f'efris_company_{self.company_id}'
            await self.channel_layer.group_add(
                self.company_group_name,
                self.channel_name
            )

            # Accept connection
            await self.accept()

            # Track connection
            self.connected_at = timezone.now()
            self.last_heartbeat = self.connected_at
            await self.track_connection()

            # Send connection success message
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'message': 'Successfully connected to EFRIS real-time updates',
                'company_id': self.company_id,
                'timestamp': self.connected_at.isoformat(),
                'supported_events': [
                    'invoice_fiscalization_started',
                    'invoice_fiscalization_completed',
                    'invoice_fiscalization_error',
                    'product_upload_started',
                    'product_upload_completed',
                    'product_upload_error',
                    'customer_tin_validated',
                    'customer_tin_validation_failed',
                    'stock_sync_completed',
                    'stock_sync_failed',
                    'queue_item_processing',
                    'queue_item_completed',
                    'health_check_completed',
                    'dictionary_sync_completed',
                    'notification',
                    'bulk_fiscalization_started',
                    'bulk_fiscalization_completed',
                    'bulk_fiscalization_error'
                ]
            }))

            logger.info(f"EFRIS WebSocket connected: user {self.user.id}, company {self.company_id}")

        except Exception as e:
            logger.error(f"EFRIS WebSocket connection failed: {e}")
            await self.close(code=4000)

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        try:
            # Leave company group
            if self.company_group_name:
                await self.channel_layer.group_discard(
                    self.company_group_name,
                    self.channel_name
                )

            # Track disconnection
            await self.track_disconnection(close_code)

            logger.info(
                f"EFRIS WebSocket disconnected: user {getattr(self.user, 'id', 'unknown')}, company {self.company_id}, code {close_code}")

        except Exception as e:
            logger.error(f"EFRIS WebSocket disconnection error: {e}")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            # Handle heartbeat
            if message_type == 'heartbeat':
                await self.handle_heartbeat(data)

            # Handle subscription management
            elif message_type == 'subscribe':
                await self.handle_subscription(data)

            elif message_type == 'unsubscribe':
                await self.handle_unsubscription(data)

            # Handle EFRIS operation requests
            elif message_type == 'request_status':
                await self.handle_status_request(data)

            else:
                logger.warning(f"Unknown message type received: {message_type}")
                await self.send_error('Unknown message type', message_type)

        except json.JSONDecodeError:
            logger.warning("Invalid JSON received in EFRIS WebSocket")
            await self.send_error('Invalid JSON format')

        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
            await self.send_error('Internal error processing message')

    # Group message handlers
    async def efris_event(self, event):
        """Handle EFRIS events from the group"""
        try:
            # Check if user is still authenticated and has access
            if not await self.verify_active_session():
                await self.close(code=4002)  # Session expired
                return

            # Send event to WebSocket
            await self.send(text_data=json.dumps({
                'type': 'efris_event',
                'event_type': event['event_type'],
                'data': event['data'],
                'timestamp': event.get('timestamp', timezone.now().isoformat())
            }))

            # Track event delivery
            await self.track_event_delivery(event['event_type'])

        except Exception as e:
            logger.error(f"Error sending EFRIS event: {e}")

    # Helper methods
    async def verify_company_access(self) -> bool:
        """Verify user has access to the company"""
        try:
            from company.models import Company
            from django.db.models import Q

            # Check if user has access to this company
            company_exists = await sync_to_async(
                Company.objects.filter(
                    Q(pk=self.company_id) &
                    (Q(owner=self.user) | Q(users=self.user) | Q(staff=self.user))
                ).exists
            )()

            return company_exists

        except Exception as e:
            logger.error(f"Error verifying company access: {e}")
            return False

    async def verify_active_session(self) -> bool:
        """Verify user session is still active"""
        try:
            if isinstance(self.user, AnonymousUser):
                return False

            # Check if user is still active
            user_active = await sync_to_async(
                lambda: self.user.is_active
            )()

            return user_active

        except Exception:
            return False

    async def handle_heartbeat(self, data: Dict[str, Any]):
        """Handle heartbeat messages"""
        self.last_heartbeat = timezone.now()

        await self.send(text_data=json.dumps({
            'type': 'heartbeat_ack',
            'timestamp': self.last_heartbeat.isoformat(),
            'server_time': timezone.now().isoformat()
        }))

    async def handle_subscription(self, data: Dict[str, Any]):
        """Handle event subscription requests"""
        event_types = data.get('events', [])

        # Store subscription preferences (could be cached or stored in DB)
        cache_key = f"efris_ws_subscription_{self.channel_name}"
        current_subs = cache.get(cache_key, [])

        for event_type in event_types:
            if event_type not in current_subs:
                current_subs.append(event_type)

        cache.set(cache_key, current_subs, timeout=3600)  # 1 hour

        await self.send(text_data=json.dumps({
            'type': 'subscription_updated',
            'subscribed_events': current_subs,
            'message': f'Subscribed to {len(event_types)} event types'
        }))

    async def handle_unsubscription(self, data: Dict[str, Any]):
        """Handle event unsubscription requests"""
        event_types = data.get('events', [])

        cache_key = f"efris_ws_subscription_{self.channel_name}"
        current_subs = cache.get(cache_key, [])

        for event_type in event_types:
            if event_type in current_subs:
                current_subs.remove(event_type)

        cache.set(cache_key, current_subs, timeout=3600)

        await self.send(text_data=json.dumps({
            'type': 'subscription_updated',
            'subscribed_events': current_subs,
            'message': f'Unsubscribed from {len(event_types)} event types'
        }))

    async def handle_status_request(self, data: Dict[str, Any]):
        """Handle requests for current EFRIS status"""
        try:
            request_type = data.get('request', 'general')

            if request_type == 'health':
                status = await self.get_health_status()
            elif request_type == 'queue':
                status = await self.get_queue_status()
            elif request_type == 'recent_operations':
                status = await self.get_recent_operations()
            else:
                status = await self.get_general_status()

            await self.send(text_data=json.dumps({
                'type': 'status_response',
                'request_type': request_type,
                'status': status,
                'timestamp': timezone.now().isoformat()
            }))

        except Exception as e:
            logger.error(f"Error handling status request: {e}")
            await self.send_error('Failed to get status information')

    async def get_health_status(self) -> Dict[str, Any]:
        """Get current EFRIS health status"""
        try:
            from .services import EFRISHealthChecker
            from company.models import Company

            company = await sync_to_async(Company.objects.get)(pk=self.company_id)
            health_checker = EFRISHealthChecker(company)

            health_status = await sync_to_async(
                health_checker.check_system_health
            )()

            return health_status

        except Exception as e:
            logger.error(f"Error getting health status: {e}")
            return {'error': 'Failed to get health status'}

    async def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status"""
        try:
            from .models import EFRISSyncQueue

            pending_count = await sync_to_async(
                EFRISSyncQueue.objects.filter(
                    company_id=self.company_id,
                    status='pending'
                ).count
            )()

            processing_count = await sync_to_async(
                EFRISSyncQueue.objects.filter(
                    company_id=self.company_id,
                    status='processing'
                ).count
            )()

            return {
                'pending_items': pending_count,
                'processing_items': processing_count,
                'total_active': pending_count + processing_count
            }

        except Exception as e:
            logger.error(f"Error getting queue status: {e}")
            return {'error': 'Failed to get queue status'}

    async def get_recent_operations(self) -> Dict[str, Any]:
        """Get recent EFRIS operations"""
        try:
            from .models import EFRISAPILog
            from datetime import timedelta

            recent_logs = await sync_to_async(list)(
                EFRISAPILog.objects.filter(
                    company_id=self.company_id,
                    created_at__gte=timezone.now() - timedelta(hours=1)
                ).order_by('-created_at')[:10].values(
                    'interface_code', 'status', 'duration_ms', 'created_at'
                )
            )

            return {
                'recent_operations': [
                    {
                        'interface_code': log['interface_code'],
                        'status': log['status'],
                        'duration_ms': log['duration_ms'],
                        'timestamp': log['created_at'].isoformat()
                    }
                    for log in recent_logs
                ]
            }

        except Exception as e:
            logger.error(f"Error getting recent operations: {e}")
            return {'error': 'Failed to get recent operations'}

    async def get_general_status(self) -> Dict[str, Any]:
        """Get general EFRIS status"""
        try:
            from company.models import Company

            company = await sync_to_async(Company.objects.get)(pk=self.company_id)

            return {
                'efris_enabled': company.efris_enabled,
                'company_name': company.display_name,
                'connection_status': 'connected',
                'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None
            }

        except Exception as e:
            logger.error(f"Error getting general status: {e}")
            return {'error': 'Failed to get general status'}

    async def send_error(self, message: str, details: str = None):
        """Send error message to client"""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': message,
            'details': details,
            'timestamp': timezone.now().isoformat()
        }))

    async def track_connection(self):
        """Track WebSocket connection for monitoring"""
        try:
            cache_key = f"efris_ws_connections_{self.company_id}"
            connections = cache.get(cache_key, [])

            connection_info = {
                'channel_name': self.channel_name,
                'user_id': self.user.id,
                'connected_at': self.connected_at.isoformat(),
                'user_agent': self.scope.get('headers', {}).get(b'user-agent', b'').decode('utf-8', 'ignore')
            }

            connections.append(connection_info)
            cache.set(cache_key, connections, timeout=3600)

        except Exception as e:
            logger.error(f"Error tracking connection: {e}")

    async def track_disconnection(self, close_code: int):
        """Track WebSocket disconnection"""
        try:
            cache_key = f"efris_ws_connections_{self.company_id}"
            connections = cache.get(cache_key, [])

            # Remove this connection
            connections = [
                conn for conn in connections
                if conn.get('channel_name') != self.channel_name
            ]

            cache.set(cache_key, connections, timeout=3600)

            # Log disconnection statistics
            if self.connected_at:
                duration = timezone.now() - self.connected_at
                logger.info(f"EFRIS WebSocket session duration: {duration.total_seconds():.2f} seconds")

        except Exception as e:
            logger.error(f"Error tracking disconnection: {e}")

    async def track_event_delivery(self, event_type: str):
        """Track event delivery for monitoring"""
        try:
            cache_key = f"efris_ws_events_delivered_{self.company_id}"
            events = cache.get(cache_key, {})

            events[event_type] = events.get(event_type, 0) + 1
            cache.set(cache_key, events, timeout=3600)

        except Exception as e:
            logger.error(f"Error tracking event delivery: {e}")







# # JavaScript client example (to be included in templates)
# EFRIS_WEBSOCKET_CLIENT = '''
# class EFRISWebSocketClient {
#     constructor(companyId, options = {}) {
#         this.companyId = companyId;
#         this.options = {
#             autoReconnect: true,
#             heartbeatInterval: 30000, // 30 seconds
#             maxReconnectAttempts: 5,
#             reconnectDelay: 1000,
#             ...options
#         };
#
#         this.ws = null;
#         this.reconnectAttempts = 0;
#         this.heartbeatTimer = null;
#         this.eventListeners = new Map();
#         this.isConnected = false;
#     }
#
#     connect() {
#         const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
#         const wsUrl = `${protocol}//${window.location.host}/ws/efris/company/${this.companyId}/`;
#
#         this.ws = new WebSocket(wsUrl);
#
#         this.ws.onopen = (event) => {
#             console.log('EFRIS WebSocket connected');
#             this.isConnected = true;
#             this.reconnectAttempts = 0;
#             this.startHeartbeat();
#             this.trigger('connected', { timestamp: new Date().toISOString() });
#         };
#
#         this.ws.onmessage = (event) => {
#             try {
#                 const data = JSON.parse(event.data);
#                 this.handleMessage(data);
#             } catch (error) {
#                 console.error('Error parsing WebSocket message:', error);
#             }
#         };
#
#         this.ws.onclose = (event) => {
#             console.log('EFRIS WebSocket closed:', event.code, event.reason);
#             this.isConnected = false;
#             this.stopHeartbeat();
#
#             if (this.options.autoReconnect && this.reconnectAttempts < this.options.maxReconnectAttempts) {
#                 this.scheduleReconnect();
#             }
#
#             this.trigger('disconnected', { code: event.code, reason: event.reason });
#         };
#
#         this.ws.onerror = (error) => {
#             console.error('EFRIS WebSocket error:', error);
#             this.trigger('error', { error: error });
#         };
#     }
#
#     disconnect() {
#         if (this.ws) {
#             this.options.autoReconnect = false;
#             this.ws.close();
#             this.ws = null;
#         }
#         this.stopHeartbeat();
#     }
#
#     send(data) {
#         if (this.isConnected && this.ws) {
#             this.ws.send(JSON.stringify(data));
#             return true;
#         }
#         return false;
#     }
#
#     handleMessage(data) {
#         switch (data.type) {
#             case 'connection_established':
#                 this.trigger('connection_established', data);
#                 break;
#
#             case 'efris_event':
#                 this.trigger('efris_event', data);
#                 this.trigger(data.event_type, data.data);
#                 break;
#
#             case 'heartbeat_ack':
#                 // Heartbeat acknowledged
#                 break;
#
#             case 'status_response':
#                 this.trigger('status_response', data);
#                 break;
#
#             case 'subscription_updated':
#                 this.trigger('subscription_updated', data);
#                 break;
#
#             case 'error':
#                 console.error('EFRIS WebSocket server error:', data.message);
#                 this.trigger('server_error', data);
#                 break;
#
#             default:
#                 console.warn('Unknown message type:', data.type);
#         }
#     }
#
#     startHeartbeat() {
#         this.stopHeartbeat();
#         this.heartbeatTimer = setInterval(() => {
#             this.send({ type: 'heartbeat', timestamp: new Date().toISOString() });
#         }, this.options.heartbeatInterval);
#     }
#
#     stopHeartbeat() {
#         if (this.heartbeatTimer) {
#             clearInterval(this.heartbeatTimer);
#             this.heartbeatTimer = null;
#         }
#     }
#
#     scheduleReconnect() {
#         const delay = this.options.reconnectDelay * Math.pow(2, this.reconnectAttempts);
#         this.reconnectAttempts++;
#
#         console.log(`EFRIS WebSocket reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
#
#         setTimeout(() => {
#             if (!this.isConnected) {
#                 this.connect();
#             }
#         }, delay);
#     }
#
#     // Event listener management
#     on(event, callback) {
#         if (!this.eventListeners.has(event)) {
#             this.eventListeners.set(event, []);
#         }
#         this.eventListeners.get(event).push(callback);
#     }
#
#     off(event, callback) {
#         if (this.eventListeners.has(event)) {
#             const listeners = this.eventListeners.get(event);
#             const index = listeners.indexOf(callback);
#             if (index > -1) {
#                 listeners.splice(index, 1);
#             }
#         }
#     }
#
#     trigger(event, data = {}) {
#         if (this.eventListeners.has(event)) {
#             this.eventListeners.get(event).forEach(callback => {
#                 try {
#                     callback(data);
#                 } catch (error) {
#                     console.error(`Error in EFRIS event listener for '${event}':`, error);
#                 }
#             });
#         }
#     }
#
#     // Subscription management
#     subscribe(events) {
#         return this.send({
#             type: 'subscribe',
#             events: Array.isArray(events) ? events : [events]
#         });
#     }
#
#     unsubscribe(events) {
#         return this.send({
#             type: 'unsubscribe',
#             events: Array.isArray(events) ? events : [events]
#         });
#     }
#
#     // Status requests
#     requestStatus(type = 'general') {
#         return this.send({
#             type: 'request_status',
#             request: type
#         });
#     }
#
#     requestHealthStatus() {
#         return this.requestStatus('health');
#     }
#
#     requestQueueStatus() {
#         return this.requestStatus('queue');
#     }
#
#     requestRecentOperations() {
#         return this.requestStatus('recent_operations');
#     }
# }
#
# // Usage example:
# /*
# const efrisWS = new EFRISWebSocketClient(companyId, {
#     autoReconnect: true,
#     heartbeatInterval: 30000
# });
#
# // Set up event listeners
# efrisWS.on('connected', () => {
#     console.log('Connected to EFRIS real-time updates');
#     efrisWS.subscribe(['invoice_fiscalization_started', 'invoice_fiscalization_completed']);
# });
#
# efrisWS.on('invoice_fiscalization_started', (data) => {
#     console.log('Invoice fiscalization started:', data);
#     // Update UI to show processing status
# });
#
# efrisWS.on('invoice_fiscalization_completed', (data) => {
#     console.log('Invoice fiscalization completed:', data);
#     if (data.success) {
#         // Update UI with success status
#         showSuccessNotification(`Invoice ${data.invoice_number} fiscalized successfully`);
#     } else {
#         // Show error notification
#         showErrorNotification(`Fiscalization failed: ${data.message}`);
#     }
# });
#
# efrisWS.on('notification', (data) => {
#     // Handle real-time notifications
#     showNotification(data.title, data.message, data.type);
# });
#
# // Connect
# efrisWS.connect();
# */
# '''