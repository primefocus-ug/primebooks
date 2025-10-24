# # company/cache.py
# from django.core.cache import cache
# from django.utils import timezone
# from datetime import timedelta
# import json
# import hashlib
#
#
# class CompanyCache:
#     """Centralized caching for company data"""
#
#     @staticmethod
#     def get_cache_key(company_id, data_type, *args):
#         """Generate consistent cache keys"""
#         key_parts = [str(company_id), data_type] + [str(arg) for arg in args]
#         key = "_".join(key_parts)
#         return f"company_cache_{key}"
#
#     @classmethod
#     def get_dashboard_data(cls, company_id):
#         """Get cached dashboard data"""
#         cache_key = cls.get_cache_key(company_id, 'dashboard')
#         return cache.get(cache_key)
#
#     @classmethod
#     def set_dashboard_data(cls, company_id, data, timeout=300):
#         """Cache dashboard data for 5 minutes"""
#         cache_key = cls.get_cache_key(company_id, 'dashboard')
#         cache.set(cache_key, data, timeout)
#
#     @classmethod
#     def get_analytics_data(cls, company_id, period='30d'):
#         """Get cached analytics data"""
#         cache_key = cls.get_cache_key(company_id, 'analytics', period)
#         return cache.get(cache_key)
#
#     @classmethod
#     def set_analytics_data(cls, company_id, data, period='30d', timeout=600):
#         """Cache analytics data for 10 minutes"""
#         cache_key = cls.get_cache_key(company_id, 'analytics', period)
#         cache.set(cache_key, data, timeout)
#
#     @classmethod
#     def invalidate_company_cache(cls, company_id):
#         """Invalidate all cache for a company"""
#         patterns = [
#             cls.get_cache_key(company_id, 'dashboard'),
#             cls.get_cache_key(company_id, 'analytics', '*'),
#             cls.get_cache_key(company_id, 'reports', '*'),
#         ]
#
#         # Note: This is simplified. In production, use Redis pattern matching
#         for pattern in patterns:
#             if '*' not in pattern:
#                 cache.delete(pattern)
#
#
# # company/notifications.py
# from django.contrib.contenttypes.models import ContentType
# from django.db import models
# from django.utils import timezone
# from channels.layers import get_channel_layer
# from asgiref.sync import async_to_sync
# import json
#
#
# class NotificationManager(models.Manager):
#     def create_notification(self, recipient, title, message, notification_type='info',
#                             related_object=None, action_url=None, data=None):
#         """Create and send a notification"""
#         notification = self.create(
#             recipient=recipient,
#             title=title,
#             message=message,
#             notification_type=notification_type,
#             action_url=action_url,
#             data=data or {}
#         )
#
#         if related_object:
#             notification.content_type = ContentType.objects.get_for_model(related_object)
#             notification.object_id = related_object.pk
#             notification.save()
#
#         # Send WebSocket notification
#         self.send_websocket_notification(notification)
#
#         return notification
#
#     def send_websocket_notification(self, notification):
#         """Send notification via WebSocket"""
#         channel_layer = get_channel_layer()
#         if channel_layer:
#             async_to_sync(channel_layer.group_send)(
#                 f'notifications_{notification.recipient.id}',
#                 {
#                     'type': 'send_notification',
#                     'data': {
#                         'id': notification.id,
#                         'title': notification.title,
#                         'message': notification.message,
#                         'type': notification.notification_type,
#                         'created_at': notification.created_at.isoformat(),
#                         'action_url': notification.action_url,
#                         'data': notification.data
#                     }
#                 }
#             )
#
#
# class Notification(models.Model):
#     NOTIFICATION_TYPES = [
#         ('info', 'Information'),
#         ('warning', 'Warning'),
#         ('error', 'Error'),
#         ('success', 'Success'),
#         ('system', 'System'),
#     ]
#
#     recipient = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE)
#     title = models.CharField(max_length=255)
#     message = models.TextField()
#     notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='info')
#
#     # Optional related object
#     content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
#     object_id = models.PositiveIntegerField(null=True, blank=True)
#     content_object = models.GenericForeignKey('content_type', 'object_id')
#
#     action_url = models.URLField(blank=True, null=True)
#     data = models.JSONField(default=dict, blank=True)
#
#     is_read = models.BooleanField(default=False)
#     created_at = models.DateTimeField(auto_now_add=True)
#     read_at = models.DateTimeField(null=True, blank=True)
#
#     objects = NotificationManager()
#
#     class Meta:
#         ordering = ['-created_at']
#         indexes = [
#             models.Index(fields=['recipient', 'is_read']),
#             models.Index(fields=['created_at']),
#         ]
#
#     def mark_as_read(self):
#         """Mark notification as read"""
#         if not self.is_read:
#             self.is_read = True
#             self.read_at = timezone.now()
#             self.save(update_fields=['is_read', 'read_at'])
#
#
# # company/monitoring.py
# import psutil
# import time
# from django.core.cache import cache
# from django.db import connections
# from django.utils import timezone
# from datetime import timedelta
# import logging
#
# logger = logging.getLogger(__name__)
#
#
# class SystemMonitor:
#     """System monitoring utilities"""
#
#     @staticmethod
#     def get_system_stats():
#         """Get current system statistics"""
#         try:
#             return {
#                 'cpu_usage': psutil.cpu_percent(interval=1),
#                 'memory_usage': psutil.virtual_memory().percent,
#                 'disk_usage': psutil.disk_usage('/').percent,
#                 'active_connections': len(psutil.net_connections()),
#                 'load_average': psutil.getloadavg()[0] if hasattr(psutil, 'getloadavg') else 0,
#                 'timestamp': timezone.now().isoformat()
#             }
#         except Exception as e:
#             logger.error(f"Error getting system stats: {e}")
#             return {}
#
#     @staticmethod
#     def get_database_stats():
#         """Get database performance statistics"""
#         try:
#             db_stats = {}
#
#             for alias in connections:
#                 connection = connections[alias]
#
#                 # Get basic connection info
#                 db_stats[alias] = {
#                     'vendor': connection.vendor,
#                     'is_usable': connection.is_usable(),
#                 }
#
#                 # Performance metrics (simplified)
#                 start_time = time.time()
#                 with connection.cursor() as cursor:
#                     cursor.execute("SELECT 1")
#                 response_time = (time.time() - start_time) * 1000
#
#                 db_stats[alias]['response_time_ms'] = round(response_time, 2)
#
#             return db_stats
#         except Exception as e:
#             logger.error(f"Error getting database stats: {e}")
#             return {}
#
#     @staticmethod
#     def get_cache_stats():
#         """Get cache performance statistics"""
#         try:
#             # Redis cache stats (if using Redis)
#             cache_stats = {
#                 'status': 'connected' if cache.get('health_check') is not None else 'disconnected',
#                 'timestamp': timezone.now().isoformat()
#             }
#
#             # Test cache performance
#             test_key = 'monitor_test'
#             test_value = {'timestamp': timezone.now().isoformat()}
#
#             start_time = time.time()
#             cache.set(test_key, test_value, 60)
#             cache.get(test_key)
#             cache.delete(test_key)
#             response_time = (time.time() - start_time) * 1000
#
#             cache_stats['response_time_ms'] = round(response_time, 2)
#
#             return cache_stats
#         except Exception as e:
#             logger.error(f"Error getting cache stats: {e}")
#             return {'status': 'error', 'error': str(e)}
#
#
# class PerformanceMonitor:
#     """Performance monitoring for company operations"""
#
#     @staticmethod
#     def track_operation(operation_name, company_id=None):
#         """Decorator to track operation performance"""
#
#         def decorator(func):
#             def wrapper(*args, **kwargs):
#                 start_time = time.time()
#                 try:
#                     result = func(*args, **kwargs)
#                     success = True
#                     error = None
#                 except Exception as e:
#                     success = False
#                     error = str(e)
#                     raise
#                 finally:
#                     execution_time = (time.time() - start_time) * 1000
#                     PerformanceMonitor.log_operation(
#                         operation_name, execution_time, success,
#                         company_id, error
#                     )
#                 return result
#
#             return wrapper
#
#         return decorator
#
#     @staticmethod
#     def log_operation(operation_name, execution_time, success, company_id=None, error=None):
#         """Log operation performance"""
#         try:
#             log_data = {
#                 'operation': operation_name,
#                 'execution_time_ms': round(execution_time, 2),
#                 'success': success,
#                 'timestamp': timezone.now().isoformat(),
#                 'company_id': company_id,
#                 'error': error
#             }
#
#             # Cache recent performance data
#             cache_key = f'performance_log_{operation_name}'
#             recent_logs = cache.get(cache_key, [])
#             recent_logs.append(log_data)
#
#             # Keep only last 100 entries
#             if len(recent_logs) > 100:
#                 recent_logs = recent_logs[-100:]
#
#             cache.set(cache_key, recent_logs, 3600)  # Cache for 1 hour
#
#             # Log to Django logger
#             if success:
#                 logger.info(f"Operation {operation_name} completed in {execution_time:.2f}ms")
#             else:
#                 logger.error(f"Operation {operation_name} failed after {execution_time:.2f}ms: {error}")
#
#         except Exception as e:
#             logger.error(f"Error logging operation performance: {e}")
#
#
# # company/health_checks.py
# from django.http import JsonResponse
# from django.views import View
# from django.utils.decorators import method_decorator
# from django.views.decorators.csrf import csrf_exempt
# from django.core.cache import cache
# from django.db import connections
# import json
#
#
# @method_decorator(csrf_exempt, name='dispatch')
# class HealthCheckView(View):
#     """Health check endpoint for monitoring"""
#
#     def get(self, request):
#         health_status = {
#             'status': 'healthy',
#             'timestamp': timezone.now().isoformat(),
#             'checks': {}
#         }
#
#         # Database check
#         try:
#             for alias in connections:
#                 connection = connections[alias]
#                 with connection.cursor() as cursor:
#                     cursor.execute("SELECT 1")
#                 health_status['checks'][f'database_{alias}'] = 'healthy'
#         except Exception as e:
#             health_status['checks']['database'] = f'unhealthy: {str(e)}'
#             health_status['status'] = 'unhealthy'
#
#         # Cache check
#         try:
#             test_key = 'health_check_test'
#             cache.set(test_key, 'test_value', 60)
#             cached_value = cache.get(test_key)
#             if cached_value == 'test_value':
#                 health_status['checks']['cache'] = 'healthy'
#                 cache.delete(test_key)
#             else:
#                 health_status['checks']['cache'] = 'unhealthy: cache not working'
#                 health_status['status'] = 'unhealthy'
#         except Exception as e:
#             health_status['checks']['cache'] = f'unhealthy: {str(e)}'
#             health_status['status'] = 'unhealthy'
#
#         # System resources check
#         try:
#             system_stats = SystemMonitor.get_system_stats()
#             if system_stats.get('cpu_usage', 0) > 90:
#                 health_status['checks']['cpu'] = 'warning: high usage'
#                 health_status['status'] = 'degraded'
#             else:
#                 health_status['checks']['cpu'] = 'healthy'
#
#             if system_stats.get('memory_usage', 0) > 90:
#                 health_status['checks']['memory'] = 'warning: high usage'
#                 health_status['status'] = 'degraded'
#             else:
#                 health_status['checks']['memory'] = 'healthy'
#         except Exception as e:
#             health_status['checks']['system'] = f'unhealthy: {str(e)}'
#             health_status['status'] = 'unhealthy'
#
#         # WebSocket check
#         try:
#             from channels.layers import get_channel_layer
#             channel_layer = get_channel_layer()
#             if channel_layer:
#                 health_status['checks']['websocket'] = 'healthy'
#             else:
#                 health_status['checks']['websocket'] = 'unhealthy: no channel layer'
#                 health_status['status'] = 'degraded'
#         except Exception as e:
#             health_status['checks']['websocket'] = f'unhealthy: {str(e)}'
#             health_status['status'] = 'degraded'
#
#         # Set appropriate HTTP status code
#         if health_status['status'] == 'healthy':
#             status_code = 200
#         elif health_status['status'] == 'degraded':
#             status_code = 200  # Still operational
#         else:
#             status_code = 503  # Service unavailable
#
#         return JsonResponse(health_status, status=status_code)
#
#
# # company/middleware.py
# import time
# from django.utils.deprecation import MiddlewareMixin
# from django.core.cache import cache
# from django.utils import timezone
# import logging
#
# logger = logging.getLogger(__name__)
#
#
# class PerformanceTrackingMiddleware(MiddlewareMixin):
#     """Middleware to track request performance"""
#
#     def process_request(self, request):
#         request._start_time = time.time()
#         return None
#
#     def process_response(self, request, response):
#         if hasattr(request, '_start_time'):
#             execution_time = (time.time() - request._start_time) * 1000
#
#             # Log slow requests
#             if execution_time > 1000:  # Slower than 1 second
#                 logger.warning(
#                     f"Slow request: {request.method} {request.path} "
#                     f"took {execution_time:.2f}ms"
#                 )
#
#             # Track API endpoint performance
#             if request.path.startswith('/api/'):
#                 cache_key = f'api_performance_{request.path}'
#                 recent_times = cache.get(cache_key, [])
#                 recent_times.append(execution_time)
#
#                 # Keep only last 100 requests
#                 if len(recent_times) > 100:
#                     recent_times = recent_times[-100:]
#
#                 cache.set(cache_key, recent_times, 3600)
#
#             # Add performance header
#             response['X-Response-Time'] = f"{execution_time:.2f}ms"
#
#         return response
#
#
# class CompanyAccessMiddleware(MiddlewareMixin):
#     """Middleware to check company access and status"""
#
#     def process_request(self, request):
#         if request.user.is_authenticated and hasattr(request.user, 'company'):
#             company = request.user.company
#
#             # Update last activity
#             if company:
#                 company.update_last_activity()
#
#                 # Check if company status needs updating
#                 if self.should_check_status(company):
#                     company.check_and_update_access_status()
#
#         return None
#
#     def should_check_status(self, company):
#         """Determine if we should check company status"""
#         # Check status every 15 minutes to avoid too frequent DB updates
#         last_check_key = f'status_check_{company.company_id}'
#         last_check = cache.get(last_check_key)
#
#         if not last_check:
#             cache.set(last_check_key, timezone.now().isoformat(), 900)  # 15 minutes
#             return True
#
#         return False